export type ID = string;

export interface CatalogOption { id?: ID; value: string | number; label: string; description?: string; color_hex?: string; product_code?: string; bin?: string; bom?: string[] }
export interface CatalogAttribute { key: 'color' | string; label: string; options: CatalogOption[] }
export interface Catalog { name?: string; description?: string; attributes: CatalogAttribute[] }
export interface Configuration { color: string }
export interface ValidationResult { valid: boolean; message?: string; errors?: string[]; configuration?: Configuration; bom?: Array<{ component?: string; part_id?: string; bin_id?: string; product_code?: string }> }
export interface ConversationReply {
  reply?: string;
  message?: string;
  proposed_configuration?: Partial<Configuration>;
  configuration?: Partial<Configuration>;
  requires_confirmation?: boolean;
  order_id?: ID | null;
}

export interface Operator { id: ID; name: string; skills?: string[]; available?: boolean; status?: string; active_task_count?: number }
export interface Task {
  id: ID; order_id: ID; name: string; description?: string; status: string; sequence?: number;
  machine_id?: ID | null; machine_name?: string; instructions?: string[] | string; requires_verification?: boolean;
  assigned_operator_id?: ID | null; verification_status?: string | null; handoff_to?: string | null;
  position?: number; kind?: string; required_skill?: string; machine?: Machine | null;
}
export interface Machine { id: ID; name: string; status: string; capabilities?: string[]; current_task_id?: ID | null; adapter?: string }
export interface Order { id: ID; status: string; created_at?: string; progress?: number; configuration?: Partial<Configuration>; current_step?: string; customer_name?: string; tasks?: Task[] }
export interface Verification { id: ID; task_id: ID; order_id?: ID; outcome?: string; provider?: string; confidence?: number; reason?: string; evidence_url?: string; created_at?: string }
export interface GatewaySettings { host: string; port: number; protocol: 'http'; use_mock: boolean; enabled?: boolean; configured?: boolean; reachable?: boolean; error?: string | null; status?: string; last_checked_at?: string }
export interface GatewayTestResult { ok?: boolean; success?: boolean; reachable?: boolean; error?: string | null; status?: string; message?: string; latency_ms?: number }
export interface WsEvent { type?: string; event?: string; message?: string; [key: string]: unknown }
