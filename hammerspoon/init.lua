-- CLI (hs コマンド) を有効化
require("hs.ipc")

-- Claude for Mac: Cmd+Q 誤終了防止
-- eventtap で低レベルにキーイベントを捕捉し、
-- Claude 宛の Cmd+Q をブロックする

local quitTap = hs.eventtap.new({hs.eventtap.event.types.keyDown}, function(event)
    local flags = event:getFlags()
    local keyCode = event:getKeyCode()

    -- Cmd+Q (keyCode 12 = Q) かつ Shift なし
    if flags.cmd and not flags.shift and not flags.alt and not flags.ctrl and keyCode == 12 then
        -- フロントアプリが Claude かチェック
        local app = hs.application.frontmostApplication()
        if app and app:name() == "Claude" then
            hs.alert.show("Quit Claude: Cmd+Shift+Q", 1)
            return true  -- イベントを消費（quit を阻止）
        end
    end
    return false  -- 他はそのまま通す
end)
quitTap:start()

-- クリップボード整形 + 貼り付け: ⌃⌥⌘V
-- PDF からコピーしたテキストの余分な改行・RTF 書式を除去し、 そのまま
-- 前面アプリに Cmd+V を送って貼り付ける (= 「ペーストしてスタイルを
-- 合わせる」 の整形版。 貼り付け先で押す)。
-- hotkey での明示発火のみ（常駐監視はしない、誤爆防止 +
-- conventions/secret-handoff.md のクリップボード単一資源原則と衝突させない）。
-- 整形ロジックの正本は scripts/clipboard-cleaner.py
-- （~/.hammerspoon/init.lua → repo への symlink を辿って解決する）。
local function cleanClipboardAndPaste()
    local initPath = os.getenv("HOME") .. "/.hammerspoon/init.lua"
    local target = hs.fs.symlinkAttributes(initPath, "target")
    local repoRoot = target and target:match("^(.*)/hammerspoon/init%.lua$")
    local cleaner = repoRoot and (repoRoot .. "/scripts/clipboard-cleaner.py")
    if not cleaner or not hs.fs.attributes(cleaner) then
        hs.alert.show("clipboard-cleaner.py が見つからない\n(init.lua が repo への symlink である必要あり)", 3)
        return
    end
    local output, ok = hs.execute("/usr/bin/python3 '" .. cleaner .. "' 2>&1")
    if ok then
        -- ⌃⌥⌘ が物理的に押されたままだと合成 Cmd+V にハードウェア修飾が
        -- 合流して paste にならない (実機で確認済の罠)。 全修飾キーの
        -- 解放を待ってから送る。
        hs.alert.show(output:gsub("%s+$", "") .. " → キーを離すと貼り付け", 1.5)
        hs.timer.waitUntil(
            function()
                local m = hs.eventtap.checkKeyboardModifiers()
                return not (m.cmd or m.alt or m.ctrl or m.shift or m.fn)
            end,
            function() hs.eventtap.keyStroke({"cmd"}, "v") end,
            0.05
        )
    else
        -- 失敗時 (= クリップボードが空 等) は貼り付けない
        hs.alert.show("clipboard-cleaner 失敗: " .. output, 3)
    end
end
hs.hotkey.bind({"ctrl", "alt", "cmd"}, "V", cleanClipboardAndPaste)

-- 個人層 / マシンローカル拡張の読み込み hook
-- ~/.hammerspoon/local.lua があれば末尾で読む（無ければ何もしない）。
-- 本ファイル (= layer 1 共有設定) を fork せずに個人の binding を
-- 足せるようにするための拡張点。個人層 repo のファイルへの symlink を
-- 置く運用を想定（hooks の layer-3 chain と同じ発想）。
local localLua = os.getenv("HOME") .. "/.hammerspoon/local.lua"
if hs.fs.attributes(localLua) then
    local ok, err = pcall(dofile, localLua)
    if not ok then
        hs.alert.show("local.lua の読み込みに失敗: " .. tostring(err), 4)
    end
end
