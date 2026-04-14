import api from './api-client';

const USER_KEY = 'auditforge_user';

export interface AuthUser {
  id: number;
  username: string;
  full_name: string | null;
}

export function isAuthenticated(): boolean {
  // With httpOnly cookies, we can't check the token directly.
  // Check if we have a stored user (set on login).
  return !!localStorage.getItem(USER_KEY);
}

export function getStoredUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const { data } = await api.post('/auth/login', { username, password });
  // Token is now in httpOnly cookie — just store user info
  localStorage.setItem(USER_KEY, JSON.stringify(data.user));
  return data.user;
}

export async function logout() {
  try {
    await api.post('/auth/logout');
  } catch {
    // Best effort
  }
  localStorage.removeItem(USER_KEY);
  window.location.href = '/login';
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await api.put('/auth/change-password', { old_password: oldPassword, new_password: newPassword });
}

export async function getWsToken(): Promise<string> {
  const { data } = await api.post('/auth/ws-token');
  return data.token;
}
