/**
 * API 客户端
 * ==========
 * 统一走 /api/v1（Vite 开发服务器会代理到 FastAPI）。
 * 依据 API 契约：成功返回业务数据，失败抛 ApiError（含 code 与 message）。
 */
import axios, { AxiosError } from 'axios'

export interface User {
  id: number
  student_id: string
  name: string
  role: 'VOTER' | 'ADMIN' | 'AUDITOR'
}

export interface Candidate {
  id: number
  idx: number
  name: string
  party: string
}

export interface Position {
  id: number
  title: string
  seats: number
  candidates: Candidate[]
}

export interface Turnout {
  voted: number
  total: number
  percent: number
}

export interface Election {
  id: number
  title: string
  description: string
  status: 'scheduled' | 'open' | 'closed' | 'published'
  status_label: string
  opens_at: string | null
  closes_at: string | null
  tally_method: 'fptp' | 'irv'
  positions: Position[]
  turnout: Turnout
  my_vote_status: 'NOT_VOTED' | 'VOTED' | 'NOT_ELIGIBLE'
}

export interface VoteResult {
  receipt_code: string
  cast_at: string
  audit_seq: number
}

export interface ReceiptInfo {
  found: boolean
  message: string
  election_title?: string
  counted?: boolean
  cast_at?: string
}

export interface ResultRow {
  position_id: number
  position_title: string
  tally_method: string
  tally_label: string
  ballot_count: number
  counts: Record<string, number>
  winner_idx: number | null
  winner_name: string | null
  digest: string
  note: string
  rounds: Array<Record<string, unknown>>
}

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message)
  }
}

const TOKEN_KEY = 'election_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

const http = axios.create({ baseURL: '/api/v1', timeout: 15000 })

http.interceptors.request.use((cfg) => {
  const t = getToken()
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

function toApiError(e: unknown): ApiError {
  const err = e as AxiosError<{ detail?: string }>
  const status = err.response?.status ?? 0
  const detail = err.response?.data?.detail ?? err.message
  return new ApiError(String(status), detail, status)
}

/** 统一处理：成功返回 data，失败抛 ApiError */
async function call<T>(p: Promise<{ data: T }>): Promise<T> {
  try {
    return (await p).data
  } catch (e) {
    throw toApiError(e)
  }
}

export const api = {
  register: (student_id: string, name: string, password: string) =>
    call<User>(http.post('/auth/register', { student_id, name, password })),

  login: (student_id: string, password: string) =>
    call<{ access_token: string; user: User }>(
      http.post('/auth/login', { student_id, password }),
    ),

  me: () => call<User>(http.get('/auth/me')),

  elections: () => call<Election[]>(http.get('/elections')),

  vote: (electionId: number, positionId: number, choice: number[]) =>
    call<VoteResult>(
      http.post(`/elections/${electionId}/votes`, {
        position_id: positionId,
        choice,
      }),
    ),

  receipt: (code: string) => call<ReceiptInfo>(http.get(`/receipts/${code}`)),

  results: (electionId: number) =>
    call<{ published: boolean; status: string; message: string; results: ResultRow[] }>(
      http.get(`/elections/${electionId}/results`),
    ),

  publish: (electionId: number) =>
    call<unknown>(http.post(`/elections/${electionId}/results/publish`)),

  setStatus: (electionId: number, status: string) =>
    call<Election>(http.patch(`/elections/${electionId}/status`, { status })),

  integrity: (electionId: number) =>
    call<{ all_passed: boolean; checks: Array<{ name: string; passed: boolean; detail: string }> }>(
      http.get(`/elections/${electionId}/integrity`),
    ),

  auditVerify: () =>
    call<{ ok: boolean; length: number; first_bad_seq: number | null; message: string }>(
      http.get('/audit/verify'),
    ),
}
