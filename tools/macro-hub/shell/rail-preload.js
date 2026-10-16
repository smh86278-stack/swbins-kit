'use strict';
/* 왼쪽 아이콘 줄(rail.html)만 쓰는 다리 — 탭 고르기·순서·떼어 내기와 {active, badge, order, popped, drop} 받기. 허브·대화 화면에는 붙지 않는다. */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('rail', {
  select: tab => ipcRenderer.send('rail-select', tab),
  order: list => ipcRenderer.send('rail-order', list),
  detach: (tab, x, y) => ipcRenderer.send('rail-detach', tab, x, y),
  menu: tab => ipcRenderer.send('rail-menu', tab),
  onRail: cb => { ipcRenderer.on('rail', (_e, s) => cb(s)); ipcRenderer.send('rail-ready'); },
});
