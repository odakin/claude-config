# lib/hook-exec-probe.bash — hook の exec 検査で BASH_ENV に渡す file (実行しない・source もしない)
#
# bash は非対話で script を起動すると、 script の 1 行目より前に $BASH_ENV を読む。 ここで exit するので、
# hook は 1 行も走らずに「exec が macOS に止められないか」 だけが分かる (lib/hook-stub.sh の hook_exec_killed)。
# 規約 = conventions/hook-authoring.md#killed-hook-stub
exit 0
