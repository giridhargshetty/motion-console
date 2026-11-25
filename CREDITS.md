# Credits and third-party licences

The code in this repository is MIT licensed (see `LICENSE`). These parts come from others and keep
their own terms.

## Libraries (installed by `pip`, not included in this repo)

| Library | Used for | Licence |
| --- | --- | --- |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) (Pose Landmarker; the `.task` models download on first run) | Body tracking | Apache-2.0 |
| [pygame](https://www.pygame.org) / SDL | Graphics, sound, input | LGPL-2.1 / zlib |
| [OpenCV](https://opencv.org) (`opencv-python`) | Camera capture, image handling | Apache-2.0 |
| [NumPy](https://numpy.org) | Arrays, synthesised sounds | BSD-3-Clause |
| [pytest](https://pytest.org) | Tests | MIT |

## Art assets included in this repo

| Asset | Where | Licence |
| --- | --- | --- |
| **Quaternius** low-poly models (Ultimate RPG Items, Knight Pack) | `assets/models/quaternius/`, used in `assets/costumes/` | CC0 (public domain). See [quaternius.com](https://quaternius.com) |
| **Kenney** Animated Characters (character + zombie skin) | `assets/models/kenney/`, used in the Zombie costume | CC0 (public domain). See [kenney.nl](https://kenney.nl) |
| **Mixamo** character and boxing animations (Adobe) | Rendered frames only, in `assets/boxers/` | Royalty-free for use in projects under Adobe's Mixamo terms. The raw Mixamo files are **not** in this repo and must not be redistributed; download your own from [mixamo.com](https://www.mixamo.com) to re-render (`tools/blender/README.md`). |
| Fruit, bombs, effects, sounds, backgrounds, menus | Drawn or synthesised in code | MIT (this repo) |

## Ideas and protocols

- **DroidCam** phone video over USB (`prototype/player.py`, `DroidCamUSB`): the wire format was
  learned from the open-source [droidcam-obs-plugin](https://github.com/dev47apps/droidcam-obs-plugin)
  (GPL-2.0) and re-implemented here; no code was copied. DroidCam is a product of Dev47Apps; this
  project is not affiliated with it.
- **Fruit Slice** game ideas were inspired by
  [FPTU_Ninja_Fruit_VR](https://github.com/tunneee/FPTU_Ninja_Fruit_VR), which has no licence, so
  nothing from it was copied: the game here is written from scratch.
- **One Euro filter**: Casiez, Roussel and Vogel, "1€ Filter" (CHI 2012), implemented from the paper.
- Inspired by the [Nex Playground](https://nex.inc) console.
