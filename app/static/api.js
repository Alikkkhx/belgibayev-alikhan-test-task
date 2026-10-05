let token = null;

export function setToken(value) { token = value; }

export async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? {Authorization: `Bearer ${token}`} : {}),
      ...options.headers,
    },
  });
  if (response.status === 204) return null;
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(body.error?.message || "Запрос не выполнен");
    error.fields = body.error?.fields || {};
    error.status = response.status;
    throw error;
  }
  return body;
}
