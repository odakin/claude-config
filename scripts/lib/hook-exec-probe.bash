# lib/hook-exec-probe.bash — hook の exec 検査で BASH_ENV に渡す file (bash が $BASH_ENV として読む。 直接は実行も source もしない)
#
# bash は非対話で script を起動すると、 script の 1 行目より前に $BASH_ENV を読む。 ここで exit するので、
# hook は 1 行も走らずに「exec が macOS に止められないか」 だけが分かる (lib/hook-stub.sh の hook_exec_killed)。
# 技法の正本 = conventions/macos-exec-policy-kill.md#exec-probe / hook での使い方 = conventions/hook-authoring.md#killed-hook-stub
exit 0
