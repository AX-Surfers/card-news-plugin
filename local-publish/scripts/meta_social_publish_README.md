# Instagram & Threads 자동전송 구현 메모

구현 파일:
- `/opt/data/scripts/meta_social_publish.py`

지원 명령:
- `verify-instagram`
- `verify-threads`
- `publish-instagram-single`
- `publish-instagram-carousel` (이미지+동영상 혼합 가능, 아래 참고)
- `comment-instagram` (게시물에 댓글 작성 — pin은 API에 없음, 앱에서 수동)
- `publish-threads-text`
- `publish-threads-image`
- `publish-threads-carousel` (이미지+동영상 혼합 가능, 아래 참고)

### 캐러셀 동영상 아이템 (2026-07-08 추가)
`--image-urls-file`의 각 줄은 URL 확장자(`.mp4`/`.mov`/`.m4v`/`.webm`)로 자동
IMAGE/VIDEO 판별. 확장자 없는 호스트(예: 구글드라이브 `uc?id=...`)는 줄 앞에
`video ` 또는 `image ` 명시 필요 (`video https://drive.google.com/uc?id=XXXX`).
동영상은 트랜스코딩 대기가 있어 `INSTAGRAM_VIDEO_CONTAINER_TIMEOUT` /
`THREADS_VIDEO_CONTAINER_TIMEOUT` (기본 600초)로 폴링 타임아웃 조절 가능.

## 필요한 값

### Instagram 게시용
필수:
- `INSTAGRAM_GRAPH_TOKEN` 또는 `META_GRAPH_ACCESS_TOKEN`
- `INSTAGRAM_BUSINESS_ACCOUNT_ID`
- 게시할 `public image URL`

권장 추가값:
- `META_APP_ID`
- `META_APP_SECRET`
- `FACEBOOK_LONG_LIVED_USER_TOKEN`
- `FACEBOOK_PAGE_ID`

비고:
- 카드뉴스 캐러셀 게시를 하려면 이미지들이 **반드시 외부 공개 URL** 이어야 함
- 로컬 파일/Notion 비공개 URL은 그대로 게시에 못 씀

### Threads 게시용
필수:
- `THREADS_ACCESS_TOKEN`
- `THREADS_USER_ID`
- 텍스트 본문

이미지 게시 시 추가:
- `public image URL`

권장 추가값:
- `THREADS_APP_ID`
- `THREADS_APP_SECRET`

비고:
- Threads도 게시 시점에 미디어를 공개 URL에서 가져감

## 현재 확인된 상태

- 시스템 유저 토큰 파일 존재:
  - `/opt/data/.secrets/meta_system_user_token.txt`
- 하지만 현재 이 토큰은 Graph API에서 다음 오류로 차단 상태:
  - `OAuthException code 200`
  - `API access blocked.`
- 그래서 이 토큰으로는 현재 Instagram 자산 조회/게시 자동화까지 바로 연결 불가
- Threads 사용자 토큰은 현재 환경에서 발견되지 않음
- 공개 스토리지(R2/S3) 설정도 현재 완전하게 잡혀 있지 않음

## 추천 운영 방식

1. 카드뉴스 렌더 완료
2. 렌더 PNG를 공개 URL로 업로드
3. Instagram:
   - 다중 이미지면 `publish-instagram-carousel`
4. Threads:
   - 텍스트만 또는 대표 이미지 1장 붙여 `publish-threads-text` 또는 `publish-threads-image`
5. 성공 응답 ID를 Notion에 기록

## 예시 실행

### Instagram 검증
```bash
export INSTAGRAM_GRAPH_TOKEN='...'
export INSTAGRAM_BUSINESS_ACCOUNT_ID='1784...'
python3 /opt/data/scripts/meta_social_publish.py verify-instagram
```

### Instagram 캐러셀 게시
```bash
python3 /opt/data/scripts/meta_social_publish.py \
  publish-instagram-carousel \
  --image-urls-file /path/to/public_urls.txt \
  --caption-file /path/to/caption.txt
```

### Threads 검증
```bash
export THREADS_ACCESS_TOKEN='...'
export THREADS_USER_ID='123456789'
python3 /opt/data/scripts/meta_social_publish.py verify-threads
```

### Threads 텍스트 게시
```bash
python3 /opt/data/scripts/meta_social_publish.py \
  publish-threads-text \
  --text-file /path/to/threads_text.txt
```

### Threads 이미지 게시
```bash
python3 /opt/data/scripts/meta_social_publish.py \
  publish-threads-image \
  --image-url 'https://public.example.com/card-1.png' \
  --text-file /path/to/threads_text.txt
```

### Threads 캐러셀 게시 (이미지+동영상 혼합 가능)
```bash
# urls 파일 예: 첫 줄이 동영상이면 "video " 접두 필요
#   video https://drive.google.com/uc?id=XXXX
#   https://drive.google.com/uc?id=YYYY
python3 /opt/data/scripts/meta_social_publish.py \
  publish-threads-carousel \
  --image-urls-file /path/to/public_urls.txt \
  --text-file /path/to/threads_text.txt
```

### 게시물에 댓글 작성 (고정은 앱에서 수동)
```bash
python3 /opt/data/scripts/meta_social_publish.py \
  comment-instagram \
  --media-id '1788...' \
  --message-file /path/to/comment.txt
```
