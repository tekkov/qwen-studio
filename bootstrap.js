(function () {
  const nativeFetch = window.fetch.bind(window);
  const backend = { url: '', token: '' };

  window.QWEN_BACKEND_READY = window.__TAURI__
    ? window.__TAURI__.core.invoke('backend_config').then(config => {
        backend.url = config.url;
        backend.token = config.token;
        return config;
      })
    : Promise.resolve(backend);

  window.fetch = async (input, init = {}) => {
    if (typeof input !== 'string' || !input.startsWith('/api/')) return nativeFetch(input, init);
    await window.QWEN_BACKEND_READY;
    const headers = new Headers(init.headers || {});
    if (backend.token) headers.set('X-Qwen-Token', backend.token);
    return nativeFetch(`${backend.url}${input}`, { ...init, headers });
  };
})();
