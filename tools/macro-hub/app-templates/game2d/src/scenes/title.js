// 시작 장면 — 제목·최고 점수·시작 안내
import * as score from '../score.js';

const FONT = '"Malgun Gothic", system-ui, sans-serif';

export class TitleScene extends Phaser.Scene {
  constructor() { super('title'); }

  async create() {
    const { width: w, height: h } = this.scale;
    this.add.text(w / 2, h * 0.34, '⭐ 별 모으기', { fontFamily: FONT, fontSize: '44px', color: '#ffe08a', fontStyle: 'bold' }).setOrigin(0.5);
    const bestText = this.add.text(w / 2, h * 0.48, '최고 점수 …', { fontFamily: FONT, fontSize: '18px', color: '#c9c6d6' }).setOrigin(0.5);
    const start = this.add.text(w / 2, h * 0.64, '스페이스 · 클릭으로 시작', { fontFamily: FONT, fontSize: '20px', color: '#ffffff' }).setOrigin(0.5);
    this.tweens.add({ targets: start, alpha: 0.35, duration: 700, yoyo: true, repeat: -1 });
    const go = () => this.scene.start('play');
    this.input.keyboard.once('keydown-SPACE', go);
    this.input.once('pointerdown', go);
    bestText.setText('최고 점수 ' + (await score.best()));
  }
}
