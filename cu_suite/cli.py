"""Command Line Interface for Computer Use Suite."""
import argparse
import sys
from cu_suite.agent_facade import ComputerUseSuite

def main():
    parser = argparse.ArgumentParser(description="Computer Use Suite MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list-windows
    subparsers.add_parser("list-windows", help="List all open desktop windows")

    # inspect
    inspect_parser = subparsers.add_parser("inspect", help="Inspect active or target window UI tree")
    inspect_parser.add_argument("--window", "-w", type=str, default=None, help="Window title substring to focus before inspecting")

    # navigate
    nav_parser = subparsers.add_parser("navigate", help="Navigate browser to a URL")
    nav_parser.add_argument("url", type=str, help="Target URL")
    nav_parser.add_argument("--window", "-w", type=str, default="Brave", help="Browser window query")

    args = parser.parse_args()
    suite = ComputerUseSuite()

    if args.command == "list-windows":
        windows = suite.list_windows()
        print(f"Found {len(windows)} open windows:")
        for idx, win in enumerate(windows, 1):
            active_marker = " [ACTIVE]" if win.is_active else ""
            print(f"  {idx}. [HWND: {win.handle}] \"{win.title}\" (PID: {win.process_id}){active_marker}")

    elif args.command == "inspect":
        if args.window:
            win = suite.focus_window(args.window)
            if not win:
                print(f"Error: Window matching '{args.window}' not found.")
                sys.exit(1)
        tree_text = suite.inspect()
        print(tree_text)

    elif args.command == "navigate":
        win = suite.focus_window(args.window)
        if not win:
            print(f"Error: Window matching '{args.window}' not found.")
            sys.exit(1)
        res = suite.navigate_browser(args.url)
        print(f"Navigation result: success={res.success}, message={res.message}")

if __name__ == "__main__":
    main()
