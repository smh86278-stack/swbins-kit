# -*- coding: utf-8 -*-
"""
파일을 첨부해서 내 메일함에 넣어 준다 (폰으로 파일 옮기는 통로)
================================================================
메일 게이트웨이에는 첨부 기능이 없어서 따로 만들었다. 계정·서버·비밀번호(DPAPI)는
키트 공통 설정(저장소 맨 위 config.local.json 의 mail 갈래)을 tools\\macro-hub\\kit.py 로 그대로 읽는다.

기본 동작은 **IMAP APPEND** 다. 자기 자신에게 SMTP 로 보내면 서버 메일 규칙이
다른 폴더로 옮겨 버려서 폰에서 안 보이는 서버가 있다. APPEND 는 INBOX 에 바로 꽂으므로
폰에서 새 메일로 그냥 보인다.

사용:
  python send-file.py --subject "제목" --body "본문" --attach C:\\path\\a.crt     (받는 사람 생략 = 내 주소)
  python send-file.py --to me@example.com ... --attach a.crt --attach b.png       (여러 개)
  python send-file.py ... --smtp                                                   (진짜로 발송하고 싶을 때)
  python send-file.py ... --body-file note.txt                                     (본문을 파일에서)
"""

import argparse
import email.utils
import imaplib
import mimetypes
import os
import sys
import time
from email.message import EmailMessage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools", "macro-hub"))
import kit  # noqa: E402


def build(to_addr, subject, body, sender, attachments):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-Id"] = email.utils.make_msgid(domain=sender.split("@", 1)[-1] if "@" in sender else None)
    msg.set_content(body)

    for path in attachments:
        if not os.path.isfile(path):
            raise SystemExit("첨부할 파일이 없습니다: %s" % path)
        ctype, _ = mimetypes.guess_type(path)
        name = os.path.basename(path)
        # .crt 는 mimetypes 가 못 잡는 경우가 있다. iOS 가 프로파일로 알아보게 지정한다.
        if name.lower().endswith((".crt", ".cer", ".pem")):
            maintype, subtype = "application", "x-x509-ca-cert"
        elif ctype:
            maintype, subtype = ctype.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=name)
    return msg


def main():
    ap = argparse.ArgumentParser(description="파일을 첨부해 내 메일함에 넣는다")
    ap.add_argument("--to", default="", help="받는 사람 (생략하면 내 주소)")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body", default="")
    ap.add_argument("--body-file", default=None)
    ap.add_argument("--attach", action="append", default=[])
    ap.add_argument("--smtp", action="store_true",
                    help="IMAP APPEND 대신 실제로 SMTP 발송한다")
    ap.add_argument("--folder", default="INBOX")
    args = ap.parse_args()

    body = args.body
    if args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as f:
            body = f.read()

    cfg = kit.mail_config()
    ok, why = kit.mail_ready(cfg)
    if not ok:
        raise SystemExit(why)
    pw = kit.password(cfg)
    sender = cfg["user"]
    to_addr = args.to or sender

    msg = build(to_addr, args.subject, body, sender, args.attach)
    size_kb = len(msg.as_bytes()) / 1024.0

    if args.smtp:
        conn = kit.smtp_connect(cfg, pw)
        try:
            conn.send_message(msg)
        finally:
            try:
                conn.quit()
            except Exception:
                pass
        print("SMTP 발송 완료 → %s (%.1f KB, 첨부 %d개)" % (to_addr, size_kb, len(args.attach)))
    else:
        conn = kit.imap_connect(cfg, pw)
        try:
            typ, _ = conn.append(args.folder, "",
                                 imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            if typ != "OK":
                raise SystemExit("APPEND 실패: %s" % typ)
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        print("메일함(%s)에 넣었습니다 → %s (%.1f KB, 첨부 %d개)"
              % (args.folder, to_addr, size_kb, len(args.attach)))
    for a in args.attach:
        print("  첨부: %s" % os.path.basename(a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
