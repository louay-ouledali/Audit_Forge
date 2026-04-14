import axios from 'axios';
import { logout } from './auth';

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
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
