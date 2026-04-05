import api from './api-client';

const TOKEN_KEY = 'auditforge_token';
const USER_KEY = 'auditforge_user';

export interface AuthUser {
  id: number;
  username: string;
  full_name: string | null;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

export function getStoredUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const { data } = await api.post('/auth/login', { username, password });
  localStorage.setItem(TOKEN_KEY, data.access_token);
  localStorage.setItem(USER_KEY, JSON.stringify(data.user));
  return data.user;
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  window.location.href = '/login';
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await api.put('/auth/change-password', { old_password: oldPassword, new_password: newPassword });
}
