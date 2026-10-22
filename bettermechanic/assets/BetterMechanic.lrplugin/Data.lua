--[[ The teams, people, pictures and games that the BetterMechanic app writes for this plugin.

players.txt, one tab-separated record per line:
  d  <first team's preset id>  <second team's preset id>     (the teams chosen in the app)
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

-- the folder applications keep their data in (AppData\Roaming, ~/Library/Application Support)
function Data.base()
	local env = os and os.getenv and os.getenv('APPDATA')
	if env and env ~= '' then
		return env
	end
	-- Lightroom's "appData" is its own folder (…\Adobe\Lightroom): the one we want holds Adobe
	local ok, p = pcall(LrPathUtils.getStandardFilePath, 'appData')
	while ok and p and LrPathUtils.leafName(p) ~= 'Adobe' and LrPathUtils.parent(p) and LrPathUtils.parent(p) ~= p do
		p = LrPathUtils.parent(p)
	end
	if ok and p and LrPathUtils.leafName(p) == 'Adobe' then
		return LrPathUtils.parent(p)
	end
	return LrPathUtils.child(LrPathUtils.child(LrPathUtils.getStandardFilePath('home'), 'Library'), 'Application Support')
end

function Data.folder()
	return LrPathUtils.child(LrPathUtils.child(Data.base(), 'BetterMechanic'), 'lightroom')
end

function Data.parse(text, folder)
	local img = LrPathUtils.child(folder, 'img')
	local data = { teams = {}, byId = {}, games = {}, blank = LrPathUtils.child(img, 'blank.png'), headings = {},
		defaults = { '', '' } }
	for _, h in ipairs({ 'staff', 'game', 'referees', 'linesmen' }) do
		data.headings[h] = LrPathUtils.child(img, 'h_' .. h .. '.png')
	end
	local team
	for line in text:gmatch('[^\r\n]+') do
		local f = split(line, '\t')
		if f[1] == 'd' then
			data.defaults = { f[2] or '', f[3] or '' }
		elseif f[1] == 't' then
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
