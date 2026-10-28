# Framekeep — Instagram 사진 저장 웹앱

공개 인스타그램 게시물(`/p/`) 및 이미지가 포함된 릴스/TV 게시물 URL을 입력해 사진만 ZIP으로 저장하는 **개인용 웹앱**입니다. `gallery-dl`을 서버에서 실행합니다.

> **중요:** GitHub Pages만으로는 인스타그램 링크를 읽어 사진을 자동 추출할 수 없습니다. GitHub Pages는 정적 사이트이므로 별도의 Python 백엔드가 필요합니다. 가장 간단한 방법은 **GitHub 저장소 1개 + Render 웹 서비스 1개**입니다.

## 1. 가장 쉬운 배포 — GitHub → Render (권장)

이 방법은 화면과 서버가 같은 주소에서 동작합니다. **GitHub Pages 설정이 필요 없습니다.**

1. GitHub에서 새 저장소(예: `framekeep`)를 만듭니다.
2. 이 ZIP의 **폴더 안 파일 전체**를 저장소 루트에 업로드합니다. `server.py`, `requirements.txt`, `docs/index.html`이 그대로 있어야 합니다.
3. [Render](https://dashboard.render.com/)에 GitHub로 로그인하고 **New → Web Service**를 선택합니다.
4. 저장소를 연결하고 다음 항목을 설정합니다.

   | 설정 | 입력값 |
   | --- | --- |
   | Language | Python 3 |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 160` |
   | Instance | Free(가능한 경우) |

   또는 Render의 **New → Blueprint**로 `render.yaml`을 사용해 설정을 불러올 수도 있습니다.
5. 배포된 Render 주소(예: `https://framekeep-abc.onrender.com`)를 엽니다.
6. 인스타그램 공개 게시물 링크를 넣고 **사진 다운로드**를 누릅니다.

무료 Render 인스턴스는 비활성 상태가 지속되면 잠들 수 있어 첫 요청이 느립니다. 인스타그램 측 차단으로 내려받기가 실패할 수 있습니다.

## 2. GitHub Pages 화면 + Render 백엔드

GitHub Pages URL (`https://아이디.github.io/저장소/`)을 별도로 사용하고 싶다면:

1. 위 지침에 따라 먼저 Render 백엔드를 배포합니다.
2. Render **Environment** 설정에서 `ALLOWED_ORIGINS`를 다음처럼 등록한 뒤 재배포합니다.

   ```
   https://아이디.github.io
   ```

   **주의:** `아이디`는 실제 GitHub 사용자명으로 바꾸고, **저장소 경로는 넣지 않습니다.** 여러 출처를 허용할 때는 쉼표로 구분합니다.
3. GitHub 저장소의 **Settings → Pages → Build and deployment**에서 `Deploy from a branch`, `main`, `/docs`를 선택하고 저장합니다.
4. 만들어진 GitHub Pages URL을 열고 **서버 연결 설정**을 펼칩니다.
5. **BACKEND URL**에 Render 서비스 주소를 입력하고 **연결 설정 저장**을 누릅니다. 이후부터 링크만 입력하면 됩니다.

> Render의 주소를 잘못 넣거나 `ALLOWED_ORIGINS`가 빠지면 CORS(교차 출처) 오류가 발생합니다. 개발자 도구의 Network/Console에서 확인할 수 있습니다.

## v1.1 대체 다운로드 안내

인스타그램이 비로그인 접근을 제한하면 자동 추출이 실패할 수 있습니다. 이것은 서버 연결 오류와 다릅니다.

1. 인스타그램에 로그인한 브라우저에서 게시물을 엽니다.
2. F12 → Network → Img → 새로고침에서 사진의 이미지 URL을 복사합니다.
3. 웹앱의 **이미지 주소로 직접 저장**을 열고 URL을 한 줄에 하나씩 입력합니다.
4. **이미지 주소로 ZIP 다운로드**를 클릭합니다.

지원 URL은 Meta 이미지 CDN(\`fbcdn.net\` / \`cdninstagram.com\`)의 HTTPS 주소입니다. URL 만료나 Render 접근 제한으로 이 기능도 실패할 수 있습니다. 로그인 쿠키나 비밀번호는 절대 입력하지 마세요.

## 3. 로컬 테스트

Python 3.10 이상 설치 후 터미널에서:

```bash
python -m pip install -r requirements.txt
python server.py
```

브라우저에서 `http://127.0.0.1:5000`을 엽니다.

단위 테스트(모의 다운로드)는 다음처럼 실행할 수 있습니다.

```bash
python -m pip install pytest
python -m pytest tests -q
```

## 4. 지원 기능

- 공개 게시물의 사진을 최고 이용 가능 해상도 기준으로 보관 시도
- 여러 장의 사진(캐러셀) 및 최대 3개 게시물 링크 입력
- 영상 파일 제외(사진만)
- 서버가 생성한 ZIP을 브라우저로 직접 전송, 게시물별로 사진 정리
- 일부 게시물 실패 시 ZIP 내부 `download_report.txt`로 안내
- 로컬 서버 및 Render 직접 배포 / GitHub Pages 연동
- 사진 파일은 임시 디렉터리에서 처리 후 삭제

**제한사항**

- 인스타그램 로그인, 스토리, 비공개 게시물, 계정 전체 다운로드 **미지원**
- 인스타그램 서버의 최고 제공 해상도일 뿐 **업로드 전 진짜 원본 파일 복구는 불가능**
- 계정 인증 요구, 빈번한 요청 차단, 네트워크 정책, 추출기 변경으로 **공개 게시물도 실패할 수 있음**
- 게시물당 이미지 최대 20장, 압축파일의 합계 이미지 용량 80MB 제한
- 요청당 게시물 최대 3개, IP별 15분당 최대 8회(단일 프로세스 제한), 동시에 2회
- 서버에서 사진을 가져오는 동안 다른 서비스를 호출하므로 배포 요금과 전송량 제한 확인 필요

## 5. 선택 사항: 공개 서버의 접근 키 보호

다른 사람이 Render의 공개 API를 대량 사용하는 것이 걱정된다면 Render 환경 변수에 다음 항목을 추가하세요.

```text
APP_ACCESS_KEY=길고_무작위적인_비밀문자열
```

그런 다음 사이트의 **서버 연결 설정 → OPTIONAL ACCESS KEY**에 **같은 키를 수동 입력**하세요. 이 키는 사용자 브라우저 저장소에 저장되며 GitHub 소스에는 기록하지 않습니다. **공개 사이트를 여러 사람과 공유할 계획이라면 접근 키 방식 대신 정식 사용자 인증과 서버 측 요청 제한을 구현하세요.**

`ALLOWED_ORIGINS`에 입력한 주소만 브라우저에서 교차 출처 요청을 보낼 수 있으며, 같은 출처의 Render 단독 배포에는 이 설정이 필요 없습니다.

## 6. 프로젝트 구조

```text
.
├── docs/
│   ├── index.html       # GitHub Pages 화면 / Render 화면
│   ├── app.js           # 요청/응답/ZIP 다운로드
│   ├── styles.css       # 반응형 스타일
│   └── favicon.svg
├── server.py            # Flask API 및 gallery-dl 실행
├── requirements.txt     # Python 라이브러리
├── render.yaml          # Render Blueprint 설정
└── tests/
    └── test_server.py
```

## 7. 주의사항

이 프로젝트는 Instagram/Meta의 공식 제품이 아닙니다. 다운로드는 개인 보관, 본인 소유 콘텐츠 또는 사용 허락을 받은 사진 등 적법한 범위에서 사용하세요. 서버에 로그인 쿠키·비밀번호를 업로드하는 기능은 넣지 않았습니다. 타인 콘텐츠 다운로드 및 재배포 시 저작권과 해당 서비스의 약관을 준수해야 합니다.

## 참고 문서

- [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)
- [Render Web Services](https://render.com/docs/web-services)
- [gallery-dl](https://github.com/mikf/gallery-dl)


## v1.2: 시간 초과 진단 및 처리 개선
- 자동 추출: 게시물당 최대 **30초**, HTTP 요청 재시도는 0회로 줄였습니다. 느린/차단된 익명 요청이 오래 지속되는 것을 방지합니다.
- 다운로드 중 시간 초과가 생겼어도 먼저 받아둔 사진은 ZIP에 보관하고 `download_report.txt`로 알려줍니다.
- 서버에서 반환한 `EXTRACTION_TIMEOUT`(HTTP 504)과 브라우저의 210초 대기시간 초과를 구분합니다.
- Network → Img의 수동 이미지 URL 다운로드는 최대 3개 요청을 병렬 처리합니다.
- 이 변경으로 인스타그램의 로그인·접근 제한이 해제되는 것은 아닙니다. CDN URL이 만료되어도 실패할 수 있습니다.
