r"""The motion console: one camera, a pose tracker, and the games.

Run from the repo root:   .venv\Scripts\python prototype\console.py
(prototype\fruit_slice.py still works and starts the same console.)

Flow (no keyboard needed):
  network screen -> calibrate -> HOME SCREEN -> game
    FRUIT SLICE: how many players?, then Classic or Survival (fruit_slice.py)
    BOXING: pick a boxer, 1 player (boxing.py, boxing_draw.py)
  The game picker is a TV-style home screen (home.py): six tiles (the games, then empty slots
  for future ones) and Settings.
Keys (for the grown-up): R rotate camera  S skeleton  D debug line  F fullscreen  Ctrl+Q quit
Remote (D-pad): arrows pick, OK starts, Esc/Back = back. Settings: prototype/config.toml

The lobby (calibration, player count, picker, tracking people) lives in fruit_slice.Game, which
also runs Fruit Slice itself; boxing borrows its tracking while it's on.
"""

import json
import sys
import time
from pathlib import Path

import pygame

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]  # prototype modules + pose_service

import fruit_slice as fs  # noqa: E402
import player as pl  # noqa: E402
from boxing import Boxing  # noqa: E402
from boxing_draw import BoxingRenderer, make_sounds as boxing_sounds  # noqa: E402
from console_setup import Setup  # noqa: E402
from home import Home, HomeRenderer  # noqa: E402
from network import Network  # noqa: E402

STOP_CONSOLE = fs.STOP_CONSOLE  # exit code for Ctrl+Q: the launcher stops instead of restarting


def keep_display_awake():
    """Stop Windows blanking the TV or sleeping while the game runs (no system setting changed)."""
    if sys.platform == "win32":
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x1, 0x2
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)


def save_scores(scores):
    try:
        fs.SCORES_FILE.write_text(json.dumps(scores))
    except OSError:
        pass


def main():
    cfg = fs.load_config()
    g = cfg["game"]

    pygame.mixer.pre_init(22050, -16, 2, 256)  # small buffer = less sound delay
    pygame.init()
    pygame.display.set_caption("Motion Console (prototype)")
    windowed = (g["window_width"], g["window_height"])
    fullscreen = g["fullscreen"]
    keep_display_awake()

    def set_mode():
        # Full screen draws at the screen's own size. On the console that's 720p: run_game.sh sets
        # the TV to 1280x720, because drawing 4K on the CPU starves pose tracking.
        pygame.mouse.set_visible(not fullscreen)
        return pygame.display.set_mode((0, 0) if fullscreen else windowed,
                                       pygame.FULLSCREEN if fullscreen else 0)

    screen = set_mode()
    tracker = pl.PoseTracker(cfg)
    game = fs.Game(cfg, fs.load_scores())   # the lobby + Fruit Slice
    renderer = fs.Renderer(cfg)
    boxing_renderer = BoxingRenderer(renderer)
    boxing = None                           # the boxing game while it's on
    home = Home(cfg)                        # the home screen (while game.state == "home")
    home_renderer = HomeRenderer(renderer)
    net = Network(cfg["network"]["backend"])
    setup = Setup(cfg, net)
    if net.available and cfg["network"]["show_at_startup"]:
        setup.open()
    sounds = fs.make_sounds() | boxing_sounds()
    clock = pygame.time.Clock()
    last_seq = 0
    perf_log = HERE.parent / "logs" / "perf.log"  # read remotely to check the box keeps up
    next_perf = time.perf_counter() + 30

    try:
        running = True
        stop_console = False
        while running:
            pick = None  # a home-screen choice this frame (by hand or remote)
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    running = False
                elif event.type != pygame.KEYDOWN:
                    continue
                # Quit is Ctrl+Q only: a remote's Back button sends Esc, which must not end the console.
                elif event.key == pygame.K_q and event.mod & pygame.KMOD_CTRL:
                    running, stop_console = False, True
                elif setup.active:
                    continue  # the setup screens use the keys themselves (typing a password)
                elif event.key == pygame.K_r:
                    tracker.cycle_rotation()
                elif event.key == pygame.K_s:
                    renderer.show_skeleton = not renderer.show_skeleton
                elif event.key == pygame.K_d:
                    renderer.show_debug = not renderer.show_debug
                elif event.key == pygame.K_f:
                    fullscreen = not fullscreen
                    screen = set_mode()
                elif boxing is not None:
                    boxing.press(event.key)
                elif game.state == "home":
                    pick = home.press(event.key)
                else:
                    game.press(event.key)

            seq, frame, people, t_pose = tracker.latest()
            fresh = seq != last_seq
            last_seq = seq
            rect, view = fs.layout(frame, screen, cfg)
            game.rotation_locked = tracker.rotation_locked
            tracker.want_people = 1 if boxing is not None else game.want_people
            tracker.recheck_rotation = game.state == "calibrate"  # follow the phone if it was turned
            now = time.perf_counter()
            if setup.active:
                dt = game.track(people, fresh, t_pose, now, view)
                hands_px = [(int(rect.x + u * rect.w), int(rect.y + v * rect.h)) for u, v in game.pointers()]
                setup.update(rect, hands_px, events, dt)
            elif boxing is not None:
                dt = game.track(people, fresh, t_pose, now, view)
                boxing.update(dt, fresh)
                if boxing.done:  # back to the home screen
                    boxing = None
                    boxing_renderer.stop_audio()
                    game.goto("home")
            else:
                dt = game.update(people, fresh, t_pose, now, view)
                if game.just_calibrated:  # the picture is right: start this way up next time
                    game.just_calibrated = False
                    tracker.remember_rotation()
                if game.want_settings:
                    game.want_settings = False
                    if net.available:
                        setup.open()
                if game.state == "home":
                    pick = home.update(game.pointers(), dt) or pick
            if pick == "fruit":
                game.start()
            elif pick == "boxing":
                boxing = Boxing(cfg, game, game.best, save_scores)
            elif pick == "settings" and net.available:
                setup.open()
            for source in (game, boxing, home):
                if source is not None:
                    for name in source.sounds:
                        if name in sounds:
                            sounds[name].play()
                    source.sounds.clear()

            # Full screen hides the mouse pointer during play; show it on the setup screens,
            # where a plugged-in mouse is one of the ways to press buttons.
            if fullscreen and pygame.mouse.get_visible() != setup.active:
                pygame.mouse.set_visible(setup.active)
            if boxing is not None and not setup.active:
                boxing_renderer.draw(screen, boxing, tracker, frame, fresh, rect, view, clock.get_fps())
            elif game.state == "home" and not setup.active:
                home_renderer.draw(screen, home, game, tracker)
            else:
                renderer.draw(screen, game, tracker, frame, fresh, people, clock.get_fps(), rect, view,
                              overlay=setup if setup.active else None)
            pygame.display.flip()
            if now >= next_perf:
                next_perf = now + 30
                state = f"boxing:{boxing.state}" if boxing is not None else game.state
                try:
                    perf_log.parent.mkdir(exist_ok=True)
                    with open(perf_log, "a") as f:
                        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} fps {clock.get_fps():.1f} "
                                f"pose_ms {tracker.pose_ms:.1f} people {len(game.present)} state {state} "
                                f"players {len(game.participants)}\n")
                except OSError:
                    pass
            clock.tick(60)
    finally:
        tracker.close()
        pygame.quit()
    # Any other ending (an update stopping the game, a crash, a stop signal that SDL turns into a
    # normal quit) returns 0 and the console launcher simply starts the game again.
    return STOP_CONSOLE if stop_console else 0


if __name__ == "__main__":
    sys.exit(main())
