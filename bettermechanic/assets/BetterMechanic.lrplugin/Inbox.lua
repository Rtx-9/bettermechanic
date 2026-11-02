--[[ Photos the BetterMechanic app sends to Lightroom (Send to Lightroom, or "Add to Lightroom" after an ingest).

The app writes a request to <data folder>/send/<name>.txt, one file path per line, renaming it into place once it
is complete. Each request is added to the catalog where the files are (nothing is copied), put in the
"BetterMechanic" collection and shown there, and then replaced by <name>.done: "<added> <already there> <failed>".
Lightroom reads the keywords, captions and ratings the app wrote into the files as it adds them.
]]

local LrDialogs = import 'LrDialogs'
local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local LrTasks = import 'LrTasks'

local Data = require 'Data'

local Inbox = { COLLECTION = 'BetterMechanic' }

function Inbox.folder()
	return LrPathUtils.child(Data.folder(), 'send')
end

-- complete requests, oldest first (the names start with the time they were sent)
function Inbox.pending(folder)
	local out = {}
	if not LrFileUtils.exists(folder) then return out end
	for path in LrFileUtils.files(folder) do
		if path:sub(-4) == '.txt' then out[#out + 1] = path end
	end
	table.sort(out)
	return out
end

-- add the files to the catalog and to the collection; false when the catalog is busy (try again later)
function Inbox.add(catalog, paths)
	local r = { added = 0, existing = 0, failed = 0, photos = {} }
	local status = catalog:withWriteAccessDo('Add Photos from BetterMechanic', function()
		for _, path in ipairs(paths) do
			local photo = catalog:findPhotoByPath(path)
			if photo then
				r.existing = r.existing + 1
			elseif LrFileUtils.exists(path) then
				local ok, added = LrTasks.pcall(catalog.addPhoto, catalog, path)
				if ok and added then
					photo, r.added = added, r.added + 1
				else
					r.failed = r.failed + 1
				end
			else
				r.failed = r.failed + 1
			end
			if photo then r.photos[#r.photos + 1] = photo end
		end
		if #r.photos > 0 then
			r.collection = catalog:createCollection(Inbox.COLLECTION, nil, true)
			r.collection:removeAllPhotos()
			r.collection:addPhotos(r.photos)
		end
	end, { timeout = 10 })
	if status == 'aborted' then return false end
	return r
end

local function photos(n)
	return n .. (n == 1 and ' photo' or ' photos') .. ' from BetterMechanic'
end

local function message(r)
	if r.existing > 0 and r.added == 0 and r.failed == 0 then
		return photos(r.existing) .. ', already in the catalog'
	end
	return 'Added ' .. photos(r.added) .. (r.existing > 0 and (', ' .. r.existing .. ' already in the catalog') or '')
		.. (r.failed > 0 and (', ' .. r.failed .. ' could not be added') or '')
end

-- take every waiting request; show the last one's photos
function Inbox.process(catalog)
	local shown
	for _, req in ipairs(Inbox.pending(Inbox.folder())) do
		local paths = {}
		for line in (LrFileUtils.readFile(req) or ''):gmatch('[^\r\n]+') do
			paths[#paths + 1] = line
		end
		local r = Inbox.add(catalog, paths)
		if not r then return end
		local fh = io.open(req:sub(1, -5) .. '.done', 'w')
		if fh then
			fh:write(r.added .. ' ' .. r.existing .. ' ' .. r.failed .. '\n')
			fh:close()
		end
		LrFileUtils.delete(req)
		if r.collection then shown = r end
		LrTasks.pcall(LrDialogs.showBezel, message(r))
	end
	if shown then
		LrTasks.pcall(function() catalog:setActiveSources({ shown.collection }) end)
		LrTasks.pcall(function() catalog:setSelectedPhotos(shown.photos[1], shown.photos) end)
	end
end

return Inbox
