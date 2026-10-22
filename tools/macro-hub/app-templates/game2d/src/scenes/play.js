// 플레이 장면 — 움직이기·떨어지는 돌·별·점수·난이도. 그림은 도형으로 직접 그린다(외부 그림 없음).
const FONT = '"Malgun Gothic", system-ui, sans-serif';

export class PlayScene extends Phaser.Scene {
  constructor() { super('play'); }

  create() {
    const { width: w, height: h } = this.scale;
    this.score = 0;
    this.speed = 160;
    this.paused = false;
    window.gameState = { running: true, score: 0 };

    this.player = this.add.rectangle(w / 2, h - 50, 46, 18, 0x8a7cf0).setStrokeStyle(2, 0xd6d0ff);
    this.physics.add.existing(this.player);
    this.player.body.setCollideWorldBounds(true).setAllowGravity(false);

    this.rocks = this.physics.add.group();
    this.stars = this.physics.add.group();
    this.physics.add.overlap(this.player, this.stars, (_, s) => this.collect(s));
    this.physics.add.overlap(this.player, this.rocks, () => this.end());

    this.scoreText = this.add.text(16, 14, '점수 0', { fontFamily: FONT, fontSize: '20px', color: '#ffffff' });
    this.levelText = this.add.text(w - 16, 14, 'Lv 1', { fontFamily: FONT, fontSize: '16px', color: '#a99cff' }).setOrigin(1, 0);

    this.keys = this.input.keyboard.createCursorKeys();
    this.input.keyboard.on('keydown-P', () => this.togglePause());
    this.input.on('pointermove', (p) => { if (!this.paused) this.player.x = Phaser.Math.Clamp(p.x, 23, w - 23); });

    this.spawnTimer = this.time.addEvent({ delay: 650, loop: true, callback: () => this.spawn() });
    this.time.addEvent({ delay: 8000, loop: true, callback: () => this.levelUp() });
  }

  spawn() {
    const w = this.scale.width;
    const x = Phaser.Math.Between(20, w - 20);
    if (Math.random() < 0.28) {
      const s = this.add.star(x, -20, 5, 7, 15, 0xffe08a);
      this.stars.add(s);
      s.body.setVelocityY(this.speed * 0.9).setAllowGravity(false);
    } else {
      const size = Phaser.Math.Between(16, 34);
      const r = this.add.rectangle(x, -20, size, size, 0x6b6878).setAngle(Phaser.Math.Between(0, 90));
      this.rocks.add(r);
      r.body.setVelocityY(this.speed + Phaser.Math.Between(0, 80)).setAllowGravity(false);
    }
  }

  collect(star) {
    star.destroy();
    this.score += 10;
    this.scoreText.setText('점수 ' + this.score);
    window.gameState.score = this.score;
    this.tweens.add({ targets: this.scoreText, scale: 1.2, duration: 80, yoyo: true });
  }

  levelUp() {
    this.speed += 40;
    this.spawnTimer.delay = Math.max(260, this.spawnTimer.delay - 60);
    this.levelText.setText('Lv ' + Math.round((this.speed - 120) / 40));
  }

  togglePause() {
    this.paused = !this.paused;
    this.physics.world.isPaused = this.paused;
    this.time.paused = this.paused;
    if (this.paused) this.pauseText = this.add.text(this.scale.width / 2, this.scale.height / 2, '일시정지 — P', { fontFamily: FONT, fontSize: '26px' }).setOrigin(0.5);
    else this.pauseText?.destroy();
  }

  end() {
    if (!window.gameState.running) return;
    window.gameState.running = false;
    this.scene.start('over', { score: this.score });
  }

  update() {
    if (this.paused) return;
    const v = 360;
    this.player.body.setVelocityX(this.keys.left.isDown ? -v : this.keys.right.isDown ? v : 0);
    const h = this.scale.height;
    for (const g of [this.rocks, this.stars]) {
      g.getChildren().forEach((o) => { if (o.y > h + 40) o.destroy(); });
    }
  }
}
