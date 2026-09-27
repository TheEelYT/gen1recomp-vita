$ErrorActionPreference = 'Stop'

$p = 'B:\gen1recomp\src\import\gba\extract_island1.lua'
$s = [System.IO.File]::ReadAllText($p)

function Replace-FirstRegex {
    param(
        [string]$Text,
        [string]$Pattern,
        [string]$Replacement,
        [string]$Label
    )

    $rx = [regex]::new($Pattern)
    $m = $rx.Match($Text)

    if (-not $m.Success) {
        throw "Could not find: $Label"
    }

    return (
        $Text.Substring(0, $m.Index) +
        $Replacement +
        $Text.Substring($m.Index + $m.Length)
    )
}

# --------------------------------------------------------------------------
# 1. Before the post-native block, build midLists while grids/borders still
#    exist, then drop the large world-map structures on Vita.
# --------------------------------------------------------------------------

if ($s -notmatch 'post-native: prepare') {

    $replacement = @'
  local function postNativeStage(name)
    progress(progressCb, 6, "post-native: " .. tostring(name), 0, 1)

    if _G.POKEPORT_VITA then
      rom:clearCache()
      collectgarbage("collect")
    end
  end

  postNativeStage("prepare")

  -- AnimPack is the final consumer of grids/borders/scriptMids. Build this
  -- small derived table now so the heavy world-map structures can die.
  local midLists = {}
  for _, pairName in ipairs(pairNames) do
    midLists[pairName] =
      NativePack.collectMidsForPair(
        grids,
        borders,
        pairName,
        scriptMids
      )
  end

  if _G.POKEPORT_VITA then
    midsByPair = nil
    midIndex = nil
    grids = nil
    borders = nil
    scriptMids = nil
    warpCells = nil

    rom:clearCache()
    collectgarbage("collect")
  end

  -- OW sprites + tileset anims + encounters + audio + chrome from ROM
'@

    $s = Replace-FirstRegex `
        $s `
        '(?m)^  -- OW sprites \+ tileset anims \+ encounters \+ audio \+ chrome from ROM\r?$' `
        $replacement `
        'post-native block marker'
}


# --------------------------------------------------------------------------
# 2. Remove the old midLists construction inside the rom2 block.
# --------------------------------------------------------------------------

if ($s -match '(?m)^    local midLists = \{\}\r?$') {

    $s = Replace-FirstRegex `
        $s `
        '(?ms)^    local midLists = \{\}\r?\n    for _, pairName in ipairs\(pairNames\) do\r?\n      midLists\[pairName\] = NativePack\.collectMidsForPair\(grids, borders, pairName, scriptMids\)\r?\n    end\r?\n' `
        '' `
        'old midLists block'
}


# --------------------------------------------------------------------------
# 3. Add exact labels to every post-native extractor.
# --------------------------------------------------------------------------

if ($s -notmatch 'postNativeStage\("help"\)') {

    $s = Replace-FirstRegex `
        $s `
        '(?m)^      require\("src\.import\.gba\.help_extract"\)\.writeExtract\(rom2, cache\)\r?$' `
        @'
      postNativeStage("help")
      require("src.import.gba.help_extract").writeExtract(rom2, cache)
'@ `
        'help extractor'

    $s = Replace-FirstRegex `
        $s `
        '(?m)^      require\("src\.import\.gba\.quest_log_extract"\)\.writeExtract\(rom2, cache\)\r?$' `
        @'
      postNativeStage("quest log")
      require("src.import.gba.quest_log_extract").writeExtract(rom2, cache)
'@ `
        'quest log extractor'

    $s = Replace-FirstRegex `
        $s `
        '(?m)^      require\("src\.import\.gba\.object_interactions_extract"\)\.writeExtract\(rom2, cache, Extract\.CACHE_ROOT, version\)\r?$' `
        @'
      postNativeStage("object interactions")
      require("src.import.gba.object_interactions_extract").writeExtract(rom2, cache, Extract.CACHE_ROOT, version)
'@ `
        'object interactions extractor'
}


# --------------------------------------------------------------------------
# 4. Tileset animation pass. After this, bundles/midLists are finished too.
# --------------------------------------------------------------------------

if ($s -notmatch 'postNativeStage\("tileset animations"\)') {

    $s = Replace-FirstRegex `
        $s `
        '(?m)^    AnimPack\.writeExtract\(rom2, cache, Extract\.CACHE_ROOT, bundles, midLists, version\)\r?$' `
        @'
    postNativeStage("tileset animations")
    AnimPack.writeExtract(rom2, cache, Extract.CACHE_ROOT, bundles, midLists, version)

    if _G.POKEPORT_VITA then
      midLists = nil
      bundles = nil
      rom2:clearCache()
      collectgarbage("collect")
    end
'@ `
        'tileset animation extractor'
}


# --------------------------------------------------------------------------
# 5. Remaining rom2 extractors.
# --------------------------------------------------------------------------

if ($s -notmatch 'postNativeStage\("overworld sprites"\)') {

    $s = Replace-FirstRegex `
        $s `
        '(?m)^      local OwExtract = require\("src\.import\.gba\.ow_extract"\)\r?$' `
        @'
      postNativeStage("overworld sprites")
      local OwExtract = require("src.import.gba.ow_extract")
'@ `
        'OW extractor'

    $s = Replace-FirstRegex `
        $s `
        '(?m)^      local EncExtract = require\("src\.import\.gba\.encounters_extract"\)\r?$' `
        @'
      postNativeStage("encounters")
      local EncExtract = require("src.import.gba.encounters_extract")
'@ `
        'encounters extractor'

    $s = Replace-FirstRegex `
        $s `
        '(?m)^      local FxExtract = require\("src\.import\.gba\.field_effect_extract"\)\r?$' `
        @'
      postNativeStage("field effects")
      local FxExtract = require("src.import.gba.field_effect_extract")
'@ `
        'field effects extractor'

    $s = Replace-FirstRegex `
        $s `
        '(?m)^        local MartsExtract = require\("src\.import\.gba\.marts_extract"\)\r?$' `
        @'
        postNativeStage("marts")
        local MartsExtract = require("src.import.gba.marts_extract")
'@ `
        'marts extractor'

    $s = Replace-FirstRegex `
        $s `
        '(?m)^        require\("src\.import\.gba\." \.\. name\)\.run\(rom2, cache, \{ cacheRoot = Extract\.CACHE_ROOT \}\)\r?$' `
        @'
        postNativeStage(name)
        require("src.import.gba." .. name).run(rom2, cache, { cacheRoot = Extract.CACHE_ROOT })
'@ `
        'auxiliary extractor loop'
}


# --------------------------------------------------------------------------
# 6. Label warps/connections and free those tables afterward.
# --------------------------------------------------------------------------

if ($s -notmatch 'postNativeStage\("write warps"\)') {

    $s = Replace-FirstRegex `
        $s `
        '(?m)^  local wl = \{ "return \{\\n" \}\r?$' `
        @'
  postNativeStage("write warps")
  local wl = { "return {\n" }
'@ `
        'warp output'

    $s = Replace-FirstRegex `
        $s `
        '(?m)^  local cl = \{ "return \{\\n" \}\r?$' `
        @'
  postNativeStage("write connections")
  local cl = { "return {\n" }
'@ `
        'connection output'

    $s = Replace-FirstRegex `
        $s `
        '(?m)^  cache:write\(Extract\.CACHE_ROOT \.\. "/connections\.lua", table\.concat\(cl\)\)\r?$' `
        @'
  cache:write(Extract.CACHE_ROOT .. "/connections.lua", table.concat(cl))

  if _G.POKEPORT_VITA then
    wl = nil
    cl = nil
    warps = nil
    connections = nil
    collectgarbage("collect")
  end
'@ `
        'connections write'
}


# --------------------------------------------------------------------------
# 7. Label the final script/trainer/map-tree work.
# --------------------------------------------------------------------------

if ($s -notmatch 'postNativeStage\("script bundle"\)') {

    $s = Replace-FirstRegex `
		$s `
		'(?m)^\s*scriptBundle\s*=\s*ExtractScripts\.writeBundleFromRom\(\r?$' `
		@'
    postNativeStage("script bundle")
    scriptBundle = ExtractScripts.writeBundleFromRom(
'@ `
		'script bundle'

    $s = Replace-FirstRegex `
        $s `
        '(?m)^      local TrainerExtract = require\("src\.import\.gba\.trainer_extract"\)\r?$' `
        @'
      if _G.POKEPORT_VITA then
        extractedScripts = nil
        rom:clearCache()
        collectgarbage("collect")
      end

      postNativeStage("trainers")
      local TrainerExtract = require("src.import.gba.trainer_extract")
'@ `
        'trainer extractor'

    $s = Replace-FirstRegex `
        $s `
        '(?m)^      local MapTreeExtract = require\("src\.import\.gba\.map_tree_extract"\)\r?$' `
        @'
      postNativeStage("map tree")
      local MapTreeExtract = require("src.import.gba.map_tree_extract")
'@ `
        'map tree extractor'
}


[System.IO.File]::WriteAllText(
    $p,
    $s,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host 'Post-native memory/progress patch applied successfully.'