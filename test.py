"""Temporary terminal UI for testing RiftFlow's game phases."""
from game_phases.after_game.service import run as run_after_game
from game_phases.before_game.service import run as run_before_game
from game_phases.in_game.service import run as run_in_game
from game_phases.out_game.service import run as run_out_game


def main():
    actions = {
        "1": run_before_game,
        "2": run_in_game,
        "3": run_after_game,
        "4": run_out_game,
    }
    while True:
        print("\nRiftFlow MVP")
        print("1. before game")
        print("2. in game")
        print("3. after game")
        print("4. out game")
        print("0. exit")
        choice = input("선택: ").strip()
        if choice == "0":
            break
        action = actions.get(choice)
        if action is None:
            print("0~4 중에서 선택하세요.")
            continue
        try:
            action()
        except Exception as error:
            print("실행 실패: %s" % error)


if __name__ == "__main__":
    main()
