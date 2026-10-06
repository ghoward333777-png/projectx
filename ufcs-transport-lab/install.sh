#!/usr/bin/env sh
# One-step install for the QueryBook UFCS-FQL Lab (Linux and macOS).
#
#   ./install.sh              install PHP, ffmpeg and zstd, check, run the tests
#   ./install.sh --minimal    PHP only (the lab runs; video features stay off)
#   ./install.sh --dry-run    print the commands without running them
#
# No Docker, Composer or database needed. Prefer containers? Use: docker compose up
set -eu

cd "$(dirname "$0")"
MINIMAL=0
DRY=0
for arg in "$@"; do
    case "$arg" in
        --minimal) MINIMAL=1 ;;
        --dry-run) DRY=1 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg (try --help)"; exit 2 ;;
    esac
done

say() { printf '\n==> %s\n' "$1"; }
run() {
    echo "    $*"
    if [ "$DRY" -eq 0 ]; then "$@"; fi
}

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
    PM=brew
elif command -v apt-get >/dev/null 2>&1; then PM=apt
elif command -v dnf >/dev/null 2>&1; then PM=dnf
elif command -v yum >/dev/null 2>&1; then PM=yum
elif command -v apk >/dev/null 2>&1; then PM=apk
elif command -v pacman >/dev/null 2>&1; then PM=pacman
elif command -v zypper >/dev/null 2>&1; then PM=zypper
else PM=unknown
fi

say "Installing for $OS (package manager: $PM)"
case "$PM" in
    brew)
        if ! command -v brew >/dev/null 2>&1; then
            echo "Homebrew is needed on macOS. Install it from https://brew.sh, then run ./install.sh again."
            exit 1
        fi
        PKGS="php"; [ "$MINIMAL" -eq 1 ] || PKGS="$PKGS ffmpeg zstd"
        # shellcheck disable=SC2086
        run brew install $PKGS
        ;;
    apt)
        PKGS="php-cli php-mbstring php-gd"; [ "$MINIMAL" -eq 1 ] || PKGS="$PKGS ffmpeg zstd"
        run $SUDO apt-get update
        # shellcheck disable=SC2086
        run $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y $PKGS
        ;;
    dnf|yum)
        PKGS="php-cli php-mbstring php-gd php-sodium php-opcache php-process"; [ "$MINIMAL" -eq 1 ] || PKGS="$PKGS zstd"
        # shellcheck disable=SC2086
        run $SUDO $PM install -y $PKGS
        if [ "$MINIMAL" -eq 0 ] && ! run $SUDO $PM install -y ffmpeg; then
            echo "    ffmpeg is not in the default repositories here: enable RPM Fusion (https://rpmfusion.org), then: $SUDO $PM install -y ffmpeg"
        fi
        ;;
    apk)
        V="$(apk search -x php83 >/dev/null 2>&1 && echo 83 || echo 82)"
        PKGS="php$V php$V-mbstring php$V-gd php$V-sodium php$V-opcache php$V-pcntl php$V-ctype"; [ "$MINIMAL" -eq 1 ] || PKGS="$PKGS ffmpeg zstd"
        # shellcheck disable=SC2086
        run $SUDO apk add $PKGS
        ;;
    pacman)
        PKGS="php php-gd php-sodium"; [ "$MINIMAL" -eq 1 ] || PKGS="$PKGS ffmpeg zstd"
        # shellcheck disable=SC2086
        run $SUDO pacman -S --needed --noconfirm $PKGS
        ;;
    zypper)
        PKGS="php8 php8-mbstring php8-gd php8-sodium php8-opcache php8-pcntl"; [ "$MINIMAL" -eq 1 ] || PKGS="$PKGS ffmpeg zstd"
        # shellcheck disable=SC2086
        run $SUDO zypper --non-interactive install $PKGS
        ;;
    *)
        echo "Could not find a supported package manager."
        echo "Install PHP 8.1+ (and optionally ffmpeg and zstd) yourself, or use Docker: docker compose up"
        exit 1
        ;;
esac

if [ "$DRY" -eq 1 ]; then
    say "Dry run: nothing was installed"
    exit 0
fi

say "Checking the install"
if ! command -v php >/dev/null 2>&1; then
    echo "PHP is still not on your PATH. Open a new terminal and run ./install.sh again."
    exit 1
fi
if ! php -r 'exit(PHP_VERSION_ID >= 80100 ? 0 : 1);'; then
    echo "This system's PHP is $(php -r 'echo PHP_VERSION;'); the lab needs 8.1 or newer."
    echo "Upgrade PHP, or use Docker instead: docker compose up"
    exit 1
fi
php bin/doctor.php || exit 1

say "Running the self-tests"
if php tests/run.php >/tmp/ufcs-lab-tests.log 2>&1; then
    echo "    all tests passed"
else
    echo "    some tests failed; details in /tmp/ufcs-lab-tests.log"
    tail -n 15 /tmp/ufcs-lab-tests.log
fi

chmod +x start.sh 2>/dev/null || true
say "Done. Start the lab with:  ./start.sh"
