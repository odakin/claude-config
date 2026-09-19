-- ClaudeReminder.applescript — 通知を「押して役に立つ」ものにするための applet。
--
-- なぜ applet が要るか:
--   `osascript -e 'display notification ...'` で出した通知は macOS が **スクリプトエディタ**の
--   通知として扱う。 通知の click は「投稿したアプリを activate する」 動作しか持たないので、
--   押すとスクリプトエディタが前面に出て空の書類選択ダイアログが開くだけで、 本文の 1 行から
--   先に進めない。 押して役に立つ通知にするには自前のアプリから投稿するしかない。
--   正本 = conventions/macos-clickable-notifications.md
--
-- 2 つの入口 (どちらも dispatch に入る):
--   (a) 投稿  : claude-notify.sh が queue に 1 行書いて `open -a` する
--               → queue があるので読んで display notification し、 queue を消す
--   (b) click : queue が無い = 人が通知を押した → ~/.claude/notify-click.sh を実行する
--
-- queue の書式 (TSV、 1 行 1 通知): title <tab> body <tab> sound
--
-- click 先の契約 (= この applet は中身を知らない):
--   ~/.claude/notify-click.sh があれば /bin/sh で実行する (install.sh --click-script が置く)。
--   無ければ ~/.claude/surface/ を開くだけ。 script の PATH は /usr/bin:/bin なので、
--   python 等を使うなら script 側で PATH を張ること。

property queueRelPath : ".claude/state/claude-notify-queue.tsv"
property clickRelPath : ".claude/notify-click.sh"
property fallbackRelPath : ".claude/surface"

on run
	my dispatch()
end run

on reopen
	-- 起動中のまま通知を押された場合 (= 投稿直後の数秒)
	my dispatch()
end reopen

on dispatch()
	set homePath to POSIX path of (path to home folder)
	set queuePath to homePath & queueRelPath
	set takenPath to queuePath & ".taken"

	set hasQueue to false
	try
		do shell script "/bin/test -s " & quoted form of queuePath
		set hasQueue to true
	end try

	if hasQueue then
		set payload to ""
		try
			-- 読む前に別名へ動かす (= 投稿中に来た次の通知を取りこぼさない)
			do shell script "/bin/mv -f " & quoted form of queuePath & " " & quoted form of takenPath
			set payload to do shell script "/bin/cat " & quoted form of takenPath & " ; /bin/rm -f " & quoted form of takenPath
		end try
		repeat with ln in paragraphs of payload
			my postOne(ln as text)
		end repeat
		-- 投稿直後に終了すると通知が配送されずに捨てられる (実測: 0.14 秒で終了し
		-- 通知設定にも登録されなかった)。 配送されるまでプロセスを生かす。
		delay 3
	else
		my openClick(homePath)
	end if
end dispatch

on postOne(ln)
	if ln is "" then return
	set savedTID to AppleScript's text item delimiters
	set AppleScript's text item delimiters to tab
	set parts to text items of ln
	set AppleScript's text item delimiters to savedTID

	set theTitle to item 1 of parts
	set theBody to ""
	if (count of parts) > 1 then set theBody to item 2 of parts
	set theSound to "Basso"
	if (count of parts) > 2 then
		if (item 3 of parts) is not "" then set theSound to item 3 of parts
	end if

	if theBody is "" then
		display notification theTitle sound name theSound
	else
		display notification theBody with title theTitle sound name theSound
	end if
end postOne

on openClick(homePath)
	try
		do shell script "/bin/sh " & quoted form of (homePath & clickRelPath)
		return
	end try
	try
		do shell script "/usr/bin/open " & quoted form of (homePath & fallbackRelPath)
	end try
end openClick
