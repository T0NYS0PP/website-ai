# TWO — kinetic typography film

参考動画（snapgram スタイル）に合わせて作った TWO のブランドムービーのレンダラー。
Python（Pillow + numpy）でフレームを生成し、ffmpeg で H.264 に書き出す。
MV 素材（Google Drive「TWO MV」）の人物を切り抜いてサーマル（熱画像風）シルエットにしている。

## 出力

- `out/TWO_mv_1440x1080_hq.mp4` — 4:3 / 24fps / 21.8s マスター（高画質）
- `out/TWO_mv_1440x1080.mp4` — 共有用の軽量エンコード
- `out/TWO_mv_960x720.mp4` — 参考動画と同じ解像度
- `out/TWO_mv_contact.png` — 1秒ごとのサムネイル

（mp4 は .gitignore 済み。下のコマンドで再生成できる）

## 構成（秒）

| 時間 | シーン | 素材 |
|---|---|---|
| 0.0 – 0.55 | 赤いカードに巨大な「TWO」、破線ガイド、ピクセルグリッチ | |
| 0.55 – 3.45 | 紙地。「TWO began with one question:」を単語ごとにタイプ、"question:" に手描きの下線 | |
| 3.45 – 6.25 | 「what does it really mean to create?」、"create?" を手描きの丸で囲む | |
| 6.25 – 9.65 | 黒地 + サーマルシルエット。「Not clothes for the sake of clothes.」 | 01.mov 2.6s〜（歩き、左右反転） |
| 9.65 – 13.05 | 「but something intentional,」→「made with purpose.」黒から白へ転じ、シルエットが影に冷える | 04.mov 1.0s〜（椅子、正面） |
| 13.05 – 16.45 | 紙地に T / W / O の文字が漂い、赤い走り書きの丸。「Each piece carries that search.」 | |
| 16.45 – 19.85 | 黒地 + サーマル。「I hope it resonates with you too.」 | 10.mov 4.6s〜（立ち姿、左右反転） |
| 19.85 – 21.8 | 紙地に巨大な「TWO」のアウトロ、"made with purpose." | |

## 再生成

```
# 素材を Drive から取得（環境の Allowed domains に drive.google.com と
# drive.usercontent.google.com が必要）
./fetch_drive.sh

# 人物切り抜き用（任意。無いときは背景差分にフォールバック）
python3 -m venv ../../.segenv && ../../.segenv/bin/pip install "rembg[cpu]"

# レンダリング
../../.segenv/bin/python render_two.py out/TWO_mv_master.mp4 --footage footage \
  --clips "01.mov@2.6:flip:scale=1.5:y=0.12,04.mov@1.0:scale=1.4:y=0.22,10.mov@4.6:flip:scale=1.15:y=0.03"
```

`--clips` の書式: `NAME@IN点秒[:flip][:scale=1.25][:y=0.04][:method=auto|rembg|plate|key][:model=u2net]`

- `flip` 左右反転（人物がテキストの方を向くように）
- `scale` フレーム高さに対するクリップの拡大率（上下はトリミング）
- `y` トリミング窓の開始位置（拡大後クリップに対する割合）
- `method` 切り抜き方法。auto は rembg があればそれを、無ければ背景差分（固定カメラで人物が動くカット向け）
- 切り抜き結果は `footage/.cache/*.npy` にキャッシュされるので、2回目以降のレンダリングは速い

素材の確認用に `./make_sheets.sh` で 480p のプロキシとタイムコード付きコンタクトシートを `proxies/` に作れる。

## 30 秒版（ナレーション + 音楽 + 実写）

`render_two_30s.py` は 21.8 秒版の見た目をそのままに、次を加えた 30 秒のカット。

- ナレーション: ElevenLabs（voice "Kirk"、eleven_v4）で台本を読み上げ、1970 年代の US ラジオ風に加工
  （230 Hz〜4.6 kHz の帯域制限、6:1 コンプ、テープ的なソフトクリップ、モノラル、微かなヒス）
- 音楽: ElevenLabs Music v2.5 の 30 秒インスト（メロウな 70s ソウルジャズのベッド）。
  ナレーション中はサイドチェインで自動的に下がる。最後のコードがエンドカードの下で鳴り終わる
- 実写: 縦素材を 4:3 に切り出し、紙とインクの二色調（元の色を 30% だけ残す）に焼き込んで挿入。
  歩きのカットは人物を切り抜いた状態からサーマルに「発火」するマッチカット、
  座りのカットは影に冷えたあと二色調の実写が「現像」される
- 文字は Scribe の単語タイムスタンプに合わせて 2 フレーム先行して出る

### 手順

```
# 1. 素材と切り抜き環境（上と同じ）
# 2. audio/ に vo_take.mp3（ナレーション）、vo_words.json（Scribe の単語タイムスタンプ）、music.mp3 を置く
python3 mix_audio.py --audio audio          # -> audio/mix.wav, audio/vo_timing.json
# 3. 実写プレートの切り出し（ungraded、1512x1134）
ffmpeg -ss 0.2  -i footage/04.mov -t 1.3 -vf "fps=24,crop=900:675:166:560,scale=1512:1134:flags=lanczos" real/Q/%04d.png
ffmpeg -ss 11.6 -i footage/10.mov -t 2.2 -vf "fps=24,crop=900:675:150:560,scale=1512:1134:flags=lanczos" real/S/%04d.png
ffmpeg -ss 15.6 -i footage/04.mov -t 3.1 -vf "fps=24,crop=900:675:166:540,scale=1512:1134:flags=lanczos" real/G/%04d.png
# 4. レンダリング
../../.segenv/bin/python render_two_30s.py out/TWO_30s.mp4 --footage footage --real real \
    --timing audio/vo_timing.json --audio audio/mix.wav
```

### 30 秒版の構成

カット点は音楽のアクセント（69.8 bpm、1.716 秒周期）の直前に置いている。

| 時間 | 内容 |
|---|---|
| 0.0 – 0.6 | 赤カードの巨大「TWO」、ラジオのチューニングノイズ |
| 0.6 – 2.9 | 紙地「TWO began with one question:」（VO 0.8〜） |
| 2.9 – 4.0 | 実写プレート: 04.mov 顎に手を当てて考える |
| 4.0 – 6.97 | 紙地「what does it really mean to create?」 |
| 6.97 – 8.68 | 紙地に切り抜いた歩く人物（01.mov）、音楽が入る |
| 8.68 – 12.12 | 発火してサーマルに。「Not clothes for the sake of clothes.」 |
| 12.12 – 15.55 | サーマルの横顔（05.mov）「but something intentional, / made with purpose.」→ 影 → 現像 |
| 15.55 – 17.3 | 実写プレート: 10.mov 刺繍の袖口に手 |
| 17.3 – 20.7 | T / W / O の文字「Each piece carries that search.」 |
| 20.7 – 24.13 | サーマルの立ち姿（10.mov、こちらを向く）「I hope it resonates with you too.」 |
| 24.13 – 27.56 | 実写プレート: 04.mov カメラを見る（ゆっくり寄る） |
| 27.56 – 30.0 | 音楽の最後のコードで巨大「TWO」、"made with purpose."、白にフェード |

## 縦型ビートカット版（2 本目の参考動画のスタイル）

`render_two_paris.py`: 1080x1920 の黒地に 4:3 の小窓。1 拍（83 bpm、0.723 秒）ごとに 1 ショット。
各ショットの間、次のショットの被写体を切り抜いた「ステッカー」が小窓の上にポップして揺れ、
カットの瞬間に落下して次のショットになる。最後は赤い「TWO」カードが落ちてきてエンドカード。

```
# 18 ショットの定義は paris/shots.txt（idx clip t_in crop）。切り出しとステッカー:
#   shots/<idx>/*.png は ffmpeg の crop + グレード、stickers/<idx>_cut.png は rembg（u2net）の切り抜き
python3 beats.py paris/beat.mp3 paris/beats.json --shots 18 --bpm 83 --tail 1.7   # ビートの格子 -> カット点
python3 mix_paris.py --music paris/beat.mp3 --beats paris/beats.json --out paris/mix.wav   # ポップ音と落下音を合成
python3 render_two_paris.py out/TWO_beatcut.mp4 --paris paris --audio paris/mix.wav
```

音楽は ElevenLabs Music v2.5 で生成した 16 秒の lo-fi hip hop（83 bpm、インスト）。出力は
`out/TWO_beatcut_1080x1920.mp4` と `out/TWO_beatcut_720x1280.mp4`。

## 必要なもの

- Python 3 + Pillow + numpy（切り抜きには rembg + onnxruntime）
- ffmpeg
- Inter フォント（`/usr/share/fonts/opentype/inter/`）
