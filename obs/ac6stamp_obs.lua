--[[
AC6 Stamp - OBS 連携スクリプト
録画を停止すると、AC6 Stamp を起動して録画ファイルの解析を自動で始めます。

使い方:
  OBS の「ツール」→「スクリプト」→「＋」でこのファイルを追加し、
  「AC6Stamp.exe の場所」を指定してください。
]]

obs = obslua
local ffi = require("ffi")

local exe_path = ""
local enabled = true
local pending_path = nil

ffi.cdef [[
int MultiByteToWideChar(unsigned int CodePage, unsigned long dwFlags, const char* lpMultiByteStr,
                        int cbMultiByte, wchar_t* lpWideCharStr, int cchWideChar);
void* ShellExecuteW(void* hwnd, const wchar_t* lpOperation, const wchar_t* lpFile,
                    const wchar_t* lpParameters, const wchar_t* lpDirectory, int nShowCmd);
]]
local shell32 = ffi.load("shell32")

-- UTF-8 → UTF-16（日本語を含むパスでも正しく渡すため）
local function wide(s)
    local n = ffi.C.MultiByteToWideChar(65001, 0, s, -1, nil, 0)
    local buf = ffi.new("wchar_t[?]", n)
    ffi.C.MultiByteToWideChar(65001, 0, s, -1, buf, n)
    return buf
end

local function last_recording_path()
    if obs.obs_frontend_get_last_recording ~= nil then
        local p = obs.obs_frontend_get_last_recording()
        if p ~= nil and p ~= "" then return p end
    end
    -- 古い OBS 向けの予備
    local out = obs.obs_frontend_get_recording_output()
    if out == nil then return nil end
    local settings = obs.obs_output_get_settings(out)
    local p = obs.obs_data_get_string(settings, "path")
    if p == "" then p = obs.obs_data_get_string(settings, "url") end
    obs.obs_data_release(settings)
    obs.obs_output_release(out)
    return p
end

local function launch()
    obs.timer_remove(launch)
    local path = pending_path
    pending_path = nil
    if path == nil or path == "" then
        obs.script_log(obs.LOG_WARNING, "[AC6Stamp] 録画ファイルの場所を取得できませんでした")
        return
    end
    path = path:gsub("/", "\\")
    local params = '--auto-run "' .. path .. '"'
    local r = shell32.ShellExecuteW(nil, wide("open"), wide(exe_path), wide(params), nil, 1)
    if tonumber(ffi.cast("intptr_t", r)) <= 32 then
        obs.script_log(obs.LOG_WARNING, "[AC6Stamp] 起動に失敗しました: " .. exe_path)
    else
        obs.script_log(obs.LOG_INFO, "[AC6Stamp] 解析を開始: " .. path)
    end
end

local function on_event(event)
    if event ~= obs.OBS_FRONTEND_EVENT_RECORDING_STOPPED then return end
    if not enabled or exe_path == "" then return end
    pending_path = last_recording_path()
    -- ファイルの書き込みが終わるのを少し待ってから起動
    obs.timer_add(launch, 3000)
end

function script_description()
    return "<b>AC6 Stamp 連携</b><br>録画を停止すると、対戦開始タイムスタンプと対戦相手名の一覧を自動で作成します。"
end

function script_properties()
    local p = obs.obs_properties_create()
    obs.obs_properties_add_bool(p, "enabled", "録画停止時に自動で解析する")
    obs.obs_properties_add_path(p, "exe_path", "AC6Stamp.exe の場所", obs.OBS_PATH_FILE,
        "AC6Stamp (AC6Stamp.exe)", nil)
    return p
end

function script_defaults(settings)
    obs.obs_data_set_default_bool(settings, "enabled", true)
end

function script_update(settings)
    enabled = obs.obs_data_get_bool(settings, "enabled")
    exe_path = obs.obs_data_get_string(settings, "exe_path"):gsub("/", "\\")
end

function script_load(settings)
    obs.obs_frontend_add_event_callback(on_event)
end
