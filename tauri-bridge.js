(function () {
  const tauri = window.__TAURI__;
  if (!tauri) return;
  const dialog = tauri.dialog;
  window.qwenDesktop = {
    chooseProjectFolder: () => dialog.open({ title: 'Link a project folder', directory: true, multiple: false }),
    chooseProjectParent: () => dialog.open({ title: 'Choose where to create the project', directory: true, multiple: false }),
    chooseAttachments: () => dialog.open({ title: 'Attach files to Qwen', multiple: true, directory: false, filters: [{ name: 'All files', extensions: ['*'] }] }).then(value => value || []),
    filePath: file => file?.path || null,
    onFileDrop: callback => {
      const webview = tauri.webview?.getCurrentWebview?.();
      if (!webview?.onDragDropEvent) return Promise.resolve(() => {});
      return webview.onDragDropEvent(event => {
        if (event.payload?.type === 'drop') callback(event.payload.paths || []);
      });
    }
  };
})();
