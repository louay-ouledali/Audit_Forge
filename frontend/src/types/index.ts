export interface Client {
  id: number;
  name: string;
  industry: string | null;
  contact_name: string | null;
  contact_email: string | null;
  notes: string | null;
  created_at: string;
  mission_count: number;
}

export interface Mission {
  id: number;
  client_id: number;
  name: string;
  description: string | null;
  start_date: string | null;
  end_date: string | null;
  status: string;
  notes: string | null;
  created_at: string;
  target_count: number;
}

export interface Target {
  id: number;
  mission_id: number;
  hostname: string | null;
  ip_address: string | null;
  target_type: string;
  os_details: string | null;
  connection_method: string | null;
  ssh_username: string | null;
  ssh_key_path: string | null;
  port: number | null;
  notes: string | null;
  created_at: string;
}

export interface Settings {
  [key: string]: string;
}
