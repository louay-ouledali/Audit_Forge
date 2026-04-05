import axios from 'axios';
import { getToken, logout } from './auth';

const api = axios.create({
  baseURL: '/api',
});

// Inject auth token
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-logout on 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !error.config.url?.includes('/auth/login')) {
      logout();
    }
    return Promise.reject(error);
  }
);

export default api;
