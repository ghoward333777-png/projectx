eSpeak NG 1.51 — bundled speech engine (Windows)
================================================
This folder holds the official eSpeak NG 1.51 64-bit Windows build, taken unchanged from the
project's release installer (espeak-ng-X64.msi, https://github.com/espeak-ng/espeak-ng/releases/tag/1.51),
trimmed to the data QueryBook uses: the 17 languages (en es fr de it pt nl sv da no fi pl cs el
ro hu ca), all language definitions and all voice variants.

  espeak-ng.exe        sha256 e6a7f1db017d838a917d79450f77138a391a31114dd6ec0855919e20db4a5149
  libespeak-ng.dll     sha256 b80ecdf4402991ea3977587bc756c8f04072e7dbb1821f0f376969ff0735bd49
  msvcp140.dll, vcruntime140.dll, vcruntime140_1.dll — Microsoft Visual C++ runtime (redistributable)

eSpeak NG is free software under the GNU General Public License version 3 or later (see COPYING).
Its source code is available at https://github.com/espeak-ng/espeak-ng (tag 1.51).
QueryBook runs it as a separate program; on macOS and Linux the system espeak-ng is used instead
(GET-VOICES-MAC.command, or: sudo apt install espeak-ng).
