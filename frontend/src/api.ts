import type { Catalog, ConfigurationRecord, Machine, Order, Review, Session, Specification, Task, User, Validation } from './types';

const base = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || '/api';
let csrf = '';
export const setCsrf = (token: string) => { csrf = token; };

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (csrf && init.method && !['GET', 'HEAD'].includes(init.method)) headers.set('X-CSRF-Token', csrf);
  const response = await fetch(`${base}${path}`, { ...init, headers, credentials: 'include' });
  const body = response.headers.get('content-type')?.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = body?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: { msg?: string }) => item.msg || JSON.stringify(item)).join('; ') : `${response.status}: Request could not be completed`);
  }
  return body as T;
}
const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });
const list = <T,>(value: T[] | { items?: T[] }) => Array.isArray(value) ? value : value.items || [];
export const api = {
  authStatus: () => request<{ needs_setup: boolean }>('/auth/status'),
  me: () => request<Session>('/auth/me'),
  login: (email: string, password: string) => request<Session>('/auth/login', json('POST', { email, password })),
  setup: (name: string, email: string, password: string) => request<Session>('/auth/setup', json('POST', { name, email, password })),
  logout: () => request('/auth/logout', json('POST', {})),
  users: async () => list(await request<User[] | { items: User[] }>('/users')),
  createUser: (body: object) => request<User>('/users', json('POST', body)),
  updateUser: (id: string, body: object) => request<User>(`/users/${encodeURIComponent(id)}`, json('PATCH', body)),
  configuration: () => request<ConfigurationRecord>('/configuration'),
  validateSpecification: (specification: Specification) => request<Validation>('/configuration/validate', json('POST', { specification })),
  saveSpecification: (specification: Specification, expected_revision: number) => request<ConfigurationRecord>('/configuration', json('PUT', { specification, expected_revision })),
  exportSpecification: () => request<Specification>('/configuration/export'),
  catalog: () => request<Catalog>('/shop/catalog'),
  validateSelection: (product_id: string, selections: Record<string, string>) => request<Validation>('/shop/validate', json('POST', { product_id, selections })),
  converse: (product_id: string, message: string, selections: Record<string, string>) => request<{ message: string; selections: Record<string, string>; requires_confirmation: boolean }>('/shop/converse', json('POST', { product_id, message, selections })),
  order: (product_id: string, selections: Record<string, string>, customer_name: string) => request<Order>('/shop/orders', json('POST', { product_id, selections, customer_name, confirmed: true })),
  orders: async () => list(await request<Order[] | { items: Order[] }>('/orders')),
  getOrder: (id: string) => request<Order>(`/orders/${encodeURIComponent(id)}`),
  machines: async () => list(await request<Machine[] | { items: Machine[] }>('/machines')),
  machineStatus: (id: string, status: string) => request<Machine>(`/machines/${encodeURIComponent(id)}`, json('PATCH', { status })),
  testGateway: () => request<{ connected?: boolean; ok?: boolean; message?: string; detail?: string }>('/gateway/test', json('POST', {})),
  tasks: async () => list(await request<Task[] | { items: Task[] }>('/operator/tasks')),
  availability: (available: boolean) => request<User>('/operator/availability', json('PATCH', { available })),
  complete: (id: string) => request<Task>(`/tasks/${encodeURIComponent(id)}/complete`, json('POST', {})),
  run: (id: string) => request<Task>(`/tasks/${encodeURIComponent(id)}/run`, json('POST', {})),
  evidence: (id: string, file: File) => { const data = new FormData(); data.append('file', file); return request<Task>(`/tasks/${encodeURIComponent(id)}/evidence`, { method: 'POST', body: data }); },
  scrap: (id: string, quantity: number, reason: string) => request<Task>(`/tasks/${encodeURIComponent(id)}/scrap`, json('POST', { quantity, reason })),
  reviews: async () => list(await request<Review[] | { items: Review[] }>('/reviews')),
  review: (id: string, decision: string, reason: string) => request(`/reviews/${encodeURIComponent(id)}`, json('POST', { decision, reason })),
};
