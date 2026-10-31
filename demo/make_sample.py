"""
데모용 분할 이미지 만들기.

이미지 생성 파이프라인이 만드는 것과 같은 형식의 파일명으로 빈 PNG를 만든다.
    {생성 프롬프트}_grid_{그리드번호}_r{행}_c{열}.png

사용법 (저장소 루트에서):
    python demo/make_sample.py          # output/splits 에 샘플 생성
    python rename.py                    # 미리보기
"""

import shutil
from pathlib import Path

SPLIT_DIR = Path("output/splits")
GRID = 4  # 그리드 1장 = 4 x 4 = 16장

# 1x1 투명 PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000005000155a1f1530000000049454e44ae426082"
)

PROMPTS = {
    "AI 모델 이미지 학습을 위한 생 무, 통무 또는 껍질째 썬 형태, 주방 단순 배경, 자연광": 2,
    "AI 모델 이미지 학습을 위한 조리 전 마른 흰쌀, 그릇과 계량컵에 담긴, 주방 단순 배경": 1,
    "AI 모델 이미지 학습을 위한 생 가지, 꼭지가 달린 통가지, 도마 위, 자연광": 1,
    "AI 모델 이미지 학습을 위한 생 베이컨, 가지런히 놓인 슬라이스, 도마 위": 2,
    "AI 모델 이미지 학습을 위한 날계란, 껍질째 계란판에 담긴, 주방 단순 배경": 1,
}


def main():
    shutil.rmtree(SPLIT_DIR, ignore_errors=True)
    SPLIT_DIR.mkdir(parents=True)
    n = 0
    for prompt, grids in PROMPTS.items():
        for g in range(1, grids + 1):
            for r in range(1, GRID + 1):
                for c in range(1, GRID + 1):
                    (SPLIT_DIR / f"{prompt}_grid_{g:03d}_r{r:02d}_c{c:02d}.png").write_bytes(PNG)
                    n += 1
    print(f"{SPLIT_DIR}/ 에 샘플 {n}장 생성")


if __name__ == "__main__":
    main()
