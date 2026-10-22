--[[ The teams, people, pictures and games that the BetterMechanic app writes for this plugin.

players.txt, one tab-separated record per line:
  t  <preset id>  <team name>  <liiga id>  <keywords added when tagging>
  p  <name>  <number>  <role, empty for players>  <picture file in img/>
  g  <date YYYY-MM-DD>  <home liiga id>  <away liiga id>  <referee|referee|...>
]]

local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'

local Data = {}

local function split(line, sep)
	local out = {}
	for field in (line .. sep):gmatch('([^' .. sep .. ']*)' .. sep) do
		out[#out + 1] = field
	end
	return out
end

function Data.folder()
	local ok, base = pcall(LrPathUtils.getStandardFilePath, 'appData')
	if not ok or not base or base == '' then
		base = os.getenv and os.getenv('APPDATA')
	end
	return LrPathUtils.child(LrPathUtils.child(base, 'BetterMechanic'), 'lightroom')
end

function Data.parse(text, folder)
	local img = LrPathUtils.child(folder, 'img')
	local data = { teams = {}, byId = {}, games = {}, blank = LrPathUtils.child(img, 'blank.png') }
	local team
	for line in text:gmatch('[^\r\n]+') do
		local f = split(line, '\t')
		if f[1] == 't' then
			team = { id = f[2], name = f[3] or '', liiga = f[4] or '', keywords = f[5] or '', people = {} }
			data.teams[#data.teams + 1] = team
			data.byId[team.id] = team
			if team.liiga == 'referees' then
				data.referees = team
			end
		elseif f[1] == 'p' and team then
			local file = f[5] or ''
			team.people[#team.people + 1] = {
				name = f[2], number = f[3] or '', role = f[4] or '', team = team,
				image = file ~= '' and LrPathUtils.child(img, file) or data.blank,
			}
		elseif f[1] == 'g' then
			local refs = {}
			for _, r in ipairs(split(f[5] or '', '|')) do
				if r ~= '' then refs[#refs + 1] = r end
			end
			data.games[#data.games + 1] = { date = f[2], teams = { f[3] or '', f[4] or '' }, refs = refs }
		end
	end
	return data
end

-- nil and the file it looked for when the app hasn't written anything yet
function Data.load()
	local folder = Data.folder()
	local path = LrPathUtils.child(folder, 'players.txt')
	if not LrFileUtils.exists(path) then
		return nil, path
	end
	return Data.parse(LrFileUtils.readFile(path), folder)
end

return Data
