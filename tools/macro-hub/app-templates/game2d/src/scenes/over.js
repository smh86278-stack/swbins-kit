// 끝 장면 — 점수 저장·최고 점수·다시 하기
import * as score from '../score.js';

const FONT = '"Malgun Gothic", system-ui, sans-serif';

export class OverScene extends Phaser.Scene {
  constructor() { super('over'); }

  async create(data) {
    const { width: w, height: h } = this.scale;
    this.add.text(w / 2, h * 0.32, '끝!', { fontFamily: FONT, fontSize: '46px', color: '#ff8f8f', fontStyle: 'bold' }).setOrigin(0.5);
    this.add.text(w / 2, h * 0.46, '점수 ' + data.score, { fontFamily: FONT, fontSize: '26px', color: '#ffffff' }).setOrigin(0.5);
    const bestText = this.add.text(w / 2, h * 0.55, '', { fontFamily: FONT, fontSize: '17px', color: '#c9c6d6' }).setOrigin(0.5);
    const again = this.add.text(w / 2, h * 0.7, '스페이스 · 클릭으로 다시', { fontFamily: FONT, fontSize: '19px', color: '#ffffff' }).setOrigin(0.5);
    this.tweens.add({ targets: again, alpha: 0.35, duration: 700, yoyo: true, repeat: -1 });
    const prev = await score.best();
    await score.save(data.score);
    bestText.setText(data.score > prev ? '🎉 새 최고 점수!' : '최고 점수 ' + prev);
    const go = () => this.scene.start('play');
    this.input.keyboard.once('keydown-SPACE', go);
    this.input.once('pointerdown', go);
  }
}
