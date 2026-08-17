const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('qwenDesktop', {
  chooseProjectFolder: () => ipcRenderer.invoke('choose-project-folder'),
  chooseProjectParent: () => ipcRenderer.invoke('choose-project-parent'),
  chooseAttachments: () => ipcRenderer.invoke('choose-attachments'),
  filePath: file => webUtils.getPathForFile(file)
});
