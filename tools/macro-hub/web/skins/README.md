# 펫 스킨 — 그림을 움직이는 이미지/영상으로 통째로 바꾸기

`web\skins\<스킨이름>\` 폴더를 만들고 안에 `skin.json` 과 이미지/영상 파일을 넣으면,
펫 우클릭 → **모습(스킨)** 메뉴와 허브 화면 위쪽 `모습` 선택칸에 그 이름이 나타나고, 어느 쪽에서 고르든 펫과 허브 화면이 같이 바뀝니다. 허브를 다시 켤 필요가 없습니다.

```
web\skins\내스킨\
  skin.json
  dog-idle.webp   dog-sleep.gif   cat-work.webm   ...
```

```json
{
  "name": "내 스킨",
  "dog": { "alert": "dog-idle.webp", "sleep": "dog-sleep.gif", "worried": "dog-sad.gif", "bark": "dog-bark.webp" },
  "cat": { "idle": "cat-idle.webp", "work": "cat-work.webm", "happy": "cat-happy.gif", "sad": "cat-sad.gif" }
}
```

## 상태 이름

| 대상 | 상태 | 언제 |
|---|---|---|
| dog (감시견) | `alert` | 상시 매크로를 지키는 중 (**기본**) |
| | `sleep` | 켜 둔 상시 매크로가 없음 |
| | `worried` | 상시 매크로가 멈춰서 다시 살리는 중 |
| | `bark` | 자동 실행이 시작되거나 알림이 왔을 때(잠깐) |
| cat (일꾼) | `idle` | 할 일 기다리는 중 (**기본**) |
| | `work` | 매크로 실행 중 |
| | `work:web` · `work:desktop` · `work:write` · `work:mail` · `work:search` | 일의 종류별 실행 중 (없으면 `work`) |
| | `happy` | 방금 성공 |
| | `sad` | 방금 실패 |

**없는 상태는 기본(`alert` / `idle`) 파일로 대신하고, 기본도 없으면 내장 그림이 나옵니다.** 일부만 만들어도 됩니다.

일의 종류별 모습은 새 그림이 없어도 `from` 으로 `work` 를 빌려 효과만 바꾸면 됩니다 — 예: `"work:search": {"from": "work", "flip": true, "fps": 9}`.
`skin_import.py` 는 `work:write`(빨리) · `work:mail`(조금 빨리) · `work:search`(반대쪽을 보며 천천히)를 이렇게 자동으로 넣습니다.
일의 종류 아이콘(머리 옆 말풍선)은 스킨과 상관없이 늘 나옵니다.

## 파일 형식과 만드는 요령

- 지원: **GIF · APNG · WebP**(움직이는 것 포함) · PNG · JPG · SVG, 영상은 **WebM · MP4**(소리 없이 반복 재생).
- **배경이 투명해야** 화면 위에 캐릭터만 떠 있습니다. GIF·APNG·WebP는 투명을 지원하고, 영상은 알파가 있는 WebM(VP9)만 투명합니다.
- 가로세로 비율은 어떤 것이든 되고, 화면에는 폭 176px(크기 설정에 따라 배율 적용)로 맞춰집니다. 선명하게 보이려면 **폭 350px 이상**으로 만드세요.
- 파일 이름은 영문·숫자·`-`·`_`·`.` 만 쓰세요. 폴더 이름도 마찬가지이고, `_` 로 시작하면 메뉴 목록에서 숨겨집니다(시험용).
- 한 상태당 한 파일입니다. 루프가 자연스럽게 이어지도록 처음과 끝 프레임을 맞추세요.

## PNG 시퀀스(프레임 목록)와 효과

한 상태의 값은 파일 이름 한 개 대신 **객체**로도 쓸 수 있습니다.

```json
"alert":   { "frames": ["dog_idle_00.png", "dog_idle_01.png", "dog_idle_02.png"], "fps": 8 },
"sleep":   { "from": "alert", "filter": "brightness(.72) saturate(.7)", "fps": 3 },
"worried": { "file": "dog-sad.gif", "flip": true, "scale": 0.9 }
```

| 키 | 뜻 |
|---|---|
| `frames` + `fps` | PNG 여러 장을 fps(초당 장수, 1~60)로 반복 재생 |
| `file` | 이미지/영상 한 개 (문자열로 바로 써도 됨) |
| `from` | 다른 상태의 모습을 빌려 오고 아래 효과만 바꿈 — 예: 대기 모습을 어둡게 해서 "잠" 대신 쓰기 |
| `filter` | CSS 필터 (`brightness(.7)`, `grayscale(1)`, `hue-rotate(40deg)` …) |
| `flip` / `scale` | 좌우 반전 / 폭 배율(1 = 기본) |

## 외부에서 받은 스프라이트 팩을 한 번에 가져오기 — `skin_import.py`

PNG 시퀀스가 든 zip(또는 풀어 둔 폴더)을 변환해서 스킨 폴더를 만들어 줍니다.

```
cd <키트 폴더>\tools\macro-hub
.venv\Scripts\python.exe skin_import.py "C:\경로\팩.zip" --list           # 무엇이 들었는지만 본다
.venv\Scripts\python.exe skin_import.py "C:\경로\팩.zip" --name catdog    # 변환해서 web\skins\catdog 를 만든다
```

- 경로·파일 이름에서 **캐릭터(cat/dog)**, **동작 이름(Idle·Walk·Jump…)**, **프레임 번호**를 읽습니다. `Idle (3).png` · `Dog_Walk_07.png` · `run1.png` 같은 이름을 다 처리합니다.
- 캐릭터마다 모든 프레임의 투명 여백을 **같은 크기로** 잘라서 동작이 바뀌어도 크기와 바닥선이 흔들리지 않게 하고, 폭을 `--max-width`(기본 360)로 줄입니다.
- 동작을 펫 상태에 자동으로 맞춥니다: `Idle`→대기, `Walk`/`Run`→고양이 일하는 중, `Jump`→성공·짖음, `Hurt`/`Fall`→실패·걱정. 팩에 없는 상태(잠 등)는 대기 모습에 어둡게 하는 효과를 입혀 대신합니다.
  연결이 마음에 안 들면 만들어진 `skin.json` 을 직접 고치면 됩니다.
- 원본이 왼쪽을 보고 있으면 `--flip`, 프레임 속도는 `--fps`, 같은 이름이 있으면 `--force`(옛 결과를 지우고 다시 만든다. `LICENSE.txt` 는 보존).
- **스프라이트 시트**(PNG 한 장 = 동작 하나, 프레임이 가로로 이어짐)는 `--sheet` — 프레임 한 변은 시트 높이로 보고, 다르면 `--frame 32` 처럼 준다.
- **도트 그림**은 `--pixel` — 정수 배로만 키워(NEAREST) 칸이 번지지 않게 하고, 화면에서도 선명하게 표시한다. 한 장짜리 자세(잠자기 등)는 숨 쉬듯 살짝 움직인다.
- 한 팩에 같은 동물이 여러 마리면(예: `Cat-1`~`Cat-6`) **`--cat-variant cat-3 --dog-variant cat-2`** 처럼 역할마다 경로에 들어 있는 글자로 고른다. 강아지 칸에 다른 고양이를 써도 된다.
- 펫 메뉴에 보일 이름은 `--title "너구리 (null painter · CC BY)"` — **출처 표기 의무가 있는 팩(CC BY)은 여기에 제작자를 적는다.**

예 (이 저장소에서 쓰는 세 가지):

```
skin_import.py CatnDog.zip --name catdog                                    # pzUH · CC0 — 전신 만화풍 고양이·강아지
skin_import.py raccoon-assets.zip --name raccoon --title "너구리 (null painter · CC BY)"
skin_import.py "Pet Cats Pack.zip" --name petcats --sheet --pixel --cat-variant cat-3 --dog-variant cat-2 --title "도트 고양이 (Luiz Melo · CC0)"
```
원본 zip 은 `web\skins\_source\` 에 보관한다(이 PC 를 옮길 때 같이 가져가거나 다시 변환하면 된다).
- 만들어진 폴더의 `LICENSE.txt` 에 **출처와 사용 조건**을 적어 두세요.

## 라이선스를 꼭 확인하세요

남이 만든 캐릭터·애니메이션은 **저작권과 사용 조건**이 각자 다릅니다(CC0 · CC BY 는 출처 표기 필요 · 상업 사용 금지 등).
회사 PC에서 쓰거나 다른 사람에게 나눠 줄 때는 조건을 지키세요. 이 저장소는 스킨 폴더를 **git 에 올리지 않습니다**(`.gitignore`) —
남의 그림이 저장소에 섞여 들어가지 않게 하려는 것입니다. 출처와 조건은 스킨 폴더 안에 `LICENSE.txt` 로 같이 두는 것을 권합니다.
