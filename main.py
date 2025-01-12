import argparse
import audioop
import gzip
import io
import json
import os
import time
from urllib.parse import quote

import pydub
import requests
from tqdm import tqdm

from type import LevelData, LevelList

SOUND_MAP = {
    3: "perfect",
    4: "flick",
    5: "sperfect",
    6: "tick",
    7: "sperfect",
    8: "flick",
    10: "critical_tap",
    11: "critical_flick",
    12: "sperfect",
    13: "critical_tick",
    14: "sperfect",
    15: "critical_flick",
}


def overlay_without_sync(seg1: pydub.AudioSegment, seg2: pydub.AudioSegment, position: int) -> pydub.AudioSegment:
    output = io.BytesIO()
    sample_width = seg1.sample_width
    spawn = seg1._spawn

    output.write(seg1[:position]._data)

    # drop down to the raw data
    bseg1 = seg1[position:]._data
    bseg2 = seg2._data
    pos = 0
    seg_max = max(len(bseg1), len(bseg2))
    bseg1 = bseg1.ljust(seg_max, b"\x00")
    bseg2 = bseg2.ljust(seg_max, b"\x00")
    output.write(audioop.add(bseg1[pos : pos + seg_max], bseg2, sample_width))
    pos += seg_max
    output.write(bseg1[pos:])

    return spawn(data=output)


def overlay_without_sync_loop(
    seg1: pydub.AudioSegment, seg2: pydub.AudioSegment, start: int, end: int
) -> pydub.AudioSegment:
    output = io.BytesIO()
    sample_width = seg1.sample_width
    spawn = seg1._spawn

    output.write(seg1[:start]._data)
    seg2_len = len(seg2)

    # drop down to the raw data
    # bseg1 = seg1[start:]._data
    # bseg2 = seg2._data
    pos = start
    while end > pos:
        current_len = min(seg2_len, end - pos)
        bseg1 = seg1[pos : pos + current_len]._data
        bseg2 = seg2[:current_len]._data
        seg_len = min(len(bseg1), len(bseg2))
        bseg1 = bseg1[:seg_len]
        bseg2 = bseg2[:seg_len]
        output.write(audioop.add(bseg1, bseg2, sample_width))
        pos += seg2_len
    output.write(seg1[end:]._data)

    return spawn(data=output)


def sync_segment(seg1, seg2):
    return seg2.set_channels(seg1.channels).set_frame_rate(seg1.frame_rate).set_sample_width(seg1.sample_width)


def color_escape(color: int):
    r, g, b = color // 65536, (color // 256) % 256, color % 256
    return f"\033[38;2;{r};{g};{b}m"


print(
    f"""
{color_escape(0x00bbd0)}== pjsekai-soundgen -----------------------------------------------------------\033[m
    {color_escape(0x00afc7)}pjsekai-soundgen / プロセカ風譜面音声生成ツール\033[m
    Version: {color_escape(0x0f6ea3)}0.2.0\033[m
    Developed by {color_escape(0x48b0d5)}名無し｡(@sevenc-nanashi)\033[m
    https://github.com/sevenc-nanashi/pjsekai-soundgen
{color_escape(0xff5a91)}-------------------------------------------------------------------------------\033[m
""".strip()
)


volume = 0.5
session = requests.Session()

proxy = '127.0.0.1:7890'
proxies = {
    'http': 'http://' + proxy,
    'https': 'http://' + proxy
}
unibotDir = 'E:/bot/unibot'

with open(f'{unibotDir}/masterdata/musicVocals.json', 'r', encoding='utf-8') as f:
    musicVocals = json.load(f)
with open(f'{unibotDir}/masterdata/musics.json', 'r', encoding='utf-8') as f:
    musics = json.load(f)

def genSound(musicid):
    total_time = time.time()
    for vocal in musicVocals:
        if vocal['musicId'] == musicid:
            name = vocal['assetbundleName']
            vocalId = vocal['id']
    bgm = pydub.AudioSegment.from_file(
        rf'{unibotDir}/data\assets\sekai\assetbundle\resources\ondemand\music\long\{name}\{name}.mp3').apply_gain(0.5)

    bgm = (
        pydub.AudioSegment.silent(duration=bgm.duration_seconds * 1000)
        .set_frame_rate(bgm.frame_rate)
        .set_channels(bgm.channels)
    )

    SEG_MAP = {
        name: sync_segment(bgm, pydub.AudioSegment.from_mp3(f"./sounds/{name}.mp3")).apply_gain(volume)
        for name in SOUND_MAP.values()
    }

    CONNECT_SEG = {
        9: sync_segment(bgm, pydub.AudioSegment.from_mp3("./sounds/connect.mp3")).apply_gain(volume),
        16: sync_segment(bgm, pydub.AudioSegment.from_mp3("./sounds/connect_critical.mp3")).apply_gain(volume),
    }

    chart_data_gzip = session.get(f"https://servers.sonolus.com/pjsekai/sonolus/levels/pjsekai-{musicid}-{vocalId}-master/data?0.2.1",
                           proxies=proxies).content
    chart_data: LevelData = json.loads(gzip.decompress(chart_data_gzip).decode("utf-8"))
    print("音声を合成中...")
    single_sounds: dict[int, set] = {}
    hold_sounds = {9: [], 16: []}
    for i, entity in enumerate(chart_data["entities"], 1):
        if entity["archetype"] < 3:
            continue
        if entity["archetype"] in [9, 16]:
            hold_sounds[entity["archetype"]].append((1, round(entity["data"]["values"][0] * 1000)))
            hold_sounds[entity["archetype"]].append((-1, round(entity["data"]["values"][3] * 1000)))
        if SOUND_MAP.get(entity["archetype"]) is None:
            continue
        if single_sounds.get(entity["archetype"]) is None:
            single_sounds[entity["archetype"]] = set()
        single_sounds[entity["archetype"]].add(round(entity["data"]["values"][0] * 1000))

    for single_sound_key, single_sound_positions in single_sounds.items():
        single_sounds[single_sound_key] = sorted(single_sound_positions)
    start_time = time.time()
    eta = "??:??"
    shift = -min(sum(single_sounds.values(), [0]))
    bgm = pydub.AudioSegment.silent(duration=shift) + bgm
    print("単ノーツの音声を生成中:")
    with tqdm(total=sum(map(len, single_sounds.values())), unit="notes", colour="#8693f6") as pbar:
        for sound, positions in single_sounds.items():
            seg = SEG_MAP[SOUND_MAP[sound]]
            for i, position in enumerate(sorted(positions)):
                play_position = position + shift
                bgm = overlay_without_sync(bgm, seg, play_position)
                pbar.update(1)

    print("\n長押しノーツの音声を生成中:")
    for ari, (archetype, slide_notes) in enumerate(hold_sounds.items(), 1):
        print(f"  {ari}/2")
        count = 0
        ranges = []
        slide_notes.sort(key=lambda x: (x[1], -x[0]))
        for diff, ntime in slide_notes:
            count += diff
            assert count >= 0
            if count == 1 and diff == 1:
                ranges.append([ntime, None])
            elif count == 0 and diff == -1:
                ranges[-1][1] = ntime
        assert count == 0

        eta = "??:??"
        for start, end in tqdm(ranges, unit="notes", colour=("#5be29c" if archetype == 9 else "#feb848")):
            if start < 0:
                start = 0
            bgm = overlay_without_sync_loop(
                bgm, CONNECT_SEG[archetype], start + shift, end + shift
            )
        print("")

    print("音声を出力中...")
    dist = f"./dist/{musicid}.mp3"
    while True:
        try:
            bgm.export(
                dist,
                format="mp3",
                bitrate="256k",
                parameters=["-minrate", "256k", "-maxrate", "256k"],
            )
        except PermissionError:
            print(f"{dist} への出力に失敗しました。ファイルへの書き込み権限があるか確認してください。10秒後に再試行します。")
            if os.name == "nt":
                print("また、ファイルが開かれている可能性もあります。")
            print("Ctrl+Cで中断します。")
            time.sleep(10)
        else:
            break
    print(f"完了しました。音声は {dist} に出力されました。")
    total_time = time.time() - start_time
    print(f"合計時間: {int(total_time / 60)}:{int(total_time % 60):02d}")

if __name__ == '__main__':
    for music in musics:
        if not os.path.exists(f"./dist/{music['id']}.mp3"):
            print(music['title'])
            genSound(music['id'])