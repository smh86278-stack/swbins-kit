'use strict';
// 렌더러(허브가 내려 준 pet.html)가 쓸 수 있는 기능을 최소한으로만 노출한다.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('petApi', {
  setIgnore: v => ipcRenderer.send('pet:ignore', !!v),
  dragBy: (dx, dy) => ipcRenderer.send('pet:drag', Number(dx) || 0, Number(dy) || 0),
  saveBounds: () => ipcRenderer.send('pet:save'),
  openHub: () => ipcRenderer.send('pet:open'),
  showMenu: () => ipcRenderer.send('pet:menu'),
  scaleBy: dir => ipcRenderer.send('pet:scale', dir > 0 ? 1 : -1),
  onAskOff: cb => ipcRenderer.on('pet:ask-off', () => cb()),
  onSetSkin: cb => ipcRenderer.on('pet:set-skin', (_e, id) => cb(id)),
  getSettings: () => ipcRenderer.invoke('pet:settings'),
  onSettings: cb => ipcRenderer.on('pet:settings', (_e, s) => cb(s)),
});
