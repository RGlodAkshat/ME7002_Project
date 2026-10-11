import type { Catalog, Configuration, ConversationReply, GatewaySettings, GatewayTestResult, Machine, Operator, Order, Task, ValidationResult, Verification } from './types';

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || '/api';

function detailFrom(body: unknown, fallback: string): string {
  if (body && typeof body === 'object') {
    const value = (body as { detail?: unknown; message?: unknown }).detail ?? (body as { message?: unknown }).message;
    if (typeof value === 'string') return value;
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { 'Content-Type': 'application/json', ...init?.headers },
  });
  const isJson = response.headers.get('content-type')?.includes('application/json');
  const body = isJson ? await response.json() : await response.text();
  if (!response.ok) throw new Error(detailFrom(body, `${response.status} ${response.statusText}`));
  return body as T;
}

function list<T>(value: T[] | { items?: T[]; data?: T[] }): T[] {
  if (Array.isArray(value)) return value;
  return value.items ?? value.data ?? [];
}

export const api = {
  getCatalog: async () => {
    const value = await request<Catalog | { product?: string; options?: Record<string, Array<string | number | Catalog['attributes'][number]['options'][number]>>; variants?: Record<string, { bom?: Array<{ bin_id?: string; product_code?: string }> }> }>('/catalog');
    if ('attributes' in value && Array.isArray(value.attributes)) return value;
    const legacy = value as { product?: string; options?: Record<string, Array<string | number | Catalog['attributes'][number]['options'][number]>>; variants?: Record<string, { bom?: Array<{ bin_id?: string; product_code?: string }> }> };
    const colors: Record<string, string> = { red: '#d4463c', green: '#3f7d5a', blue: '#2855c5', white: '#deded7' };
    return {
      name: legacy.product ?? 'Smart Fan',
      attributes: Object.entries(legacy.options ?? {}).map(([key, options]) => ({
        key,
        label: key.charAt(0).toUpperCase() + key.slice(1),
        options: options.map(option => {
          if (typeof option === 'object') return option;
          const variant = legacy.variants?.[String(option)];
          return { value: option, label: String(option), color_hex: colors[String(option)], product_code: variant?.bom?.[0]?.product_code, bom: variant?.bom?.map(item => item.bin_id).filter(Boolean) as string[] | undefined };
        }),
      })),
    } as Catalog;
  },
  validateConfiguration: (configuration: Configuration) => request<ValidationResult>('/configurations/validate', { method: 'POST', body: JSON.stringify(configuration) }),
  converse: (message: string, configuration: Partial<Configuration>, confirmed = false, customerName = 'Demo Customer') =>
    request<ConversationReply>('/configurations/converse', { method: 'POST', body: JSON.stringify({ message, current_configuration: configuration, confirmed, customer_name: customerName }) }),
  createOrder: (configuration: Configuration, customerName: string) => request<Order>('/orders', { method: 'POST', body: JSON.stringify({ customer_name: customerName, configuration, confirmed: true }) }),
  getOperators: async () => list(await request<Operator[] | { items?: Operator[]; data?: Operator[] }>('/operators')),
  getTasks: async (operatorId: string) => list(await request<Task[] | { items?: Task[]; data?: Task[] }>(`/operators/${operatorId}/tasks`)),
  taskAction: (taskId: string, action: 'accept' | 'start' | 'complete', body: object = {}) => request<Task>(`/tasks/${taskId}/${action}`, { method: 'POST', body: JSON.stringify(body) }),
  handoffTask: (taskId: string, operatorId: string) => request<Task>(`/tasks/${taskId}/handoff`, { method: 'POST', body: JSON.stringify({ to_operator_id: operatorId }) }),
  uploadEvidence: (taskId: string, file: File) => { const data = new FormData(); data.append('file', file); return request<Verification>(`/tasks/${taskId}/evidence`, { method: 'POST', body: data }); },
  verifyTask: (taskId: string) => request<unknown>(`/tasks/${taskId}/verify`, { method: 'POST', body: '{}' }),
  getMachines: async () => list(await request<Machine[] | { items?: Machine[]; data?: Machine[] }>('/machines')),
  setMachineStatus: (machineId: string, status: string) => request<Machine>(`/machines/${machineId}/status`, { method: 'PUT', body: JSON.stringify({ status }) }),
  mockMachineComplete: (machineId: string) => request<unknown>(`/mock/machines/${machineId}/complete`, { method: 'POST', body: '{}' }),
  getOrders: async () => list(await request<Order[] | { items?: Order[]; data?: Order[] }>('/orders')),
  setOperatorAvailability: (operatorId: string, available: boolean) => request<Operator>(`/operators/${operatorId}/availability`, { method: 'PUT', body: JSON.stringify({ available }) }),
  getVerifications: async () => list(await request<Verification[] | { items?: Verification[]; data?: Verification[] }>('/verifications?status=manual_review')),
  reviewVerification: (verificationId: string, decision: 'approve' | 'reject', reason: string) => request<Verification>(`/verifications/${verificationId}/review`, { method: 'POST', body: JSON.stringify({ decision, reason }) }),
  getGatewaySettings: () => request<GatewaySettings>('/settings/machine-gateway'),
  updateGatewaySettings: (settings: GatewaySettings) => request<GatewaySettings>('/settings/machine-gateway', { method: 'PUT', body: JSON.stringify({ host: settings.host, port: settings.port, protocol: settings.protocol, enabled: settings.enabled ?? true, use_mock: settings.use_mock }) }),
  testGateway: () => request<GatewayTestResult>('/settings/machine-gateway/test', { method: 'POST', body: '{}' }),
};

export function websocketUrl(): string {
  const configured = import.meta.env.VITE_WS_URL as string | undefined;
  if (configured) return configured;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws`;
}
