// 게임 설정 — 장면 셋(시작·플레이·끝). window.game 으로 두어 검사(appcheck)가 상태를 본다.
import * as score from './score.js';
import { TitleScene } from './scenes/title.js';
import { PlayScene } from './scenes/play.js';
import { OverScene } from './scenes/over.js';

await score.init();

window.game = new Phaser.Game({
  type: Phaser.AUTO,
  parent: 'game',
  width: 480,
  height: 640,
  backgroundColor: '#211f2b',
  physics: { default: 'arcade', arcade: { debug: false } },
  scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
  scene: [TitleScene, PlayScene, OverScene],
});
