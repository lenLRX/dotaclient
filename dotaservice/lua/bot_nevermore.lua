local config = require('bots/config')
local dkjson = require('game/dkjson')
local pprint = require('bots/pprint')

local ACTION_FILENAME = 'bots/action'
local LIVE_CONFIG_FILENAME = 'bots/live_config_auto'

local debug_text = nil
local live_config = nil


local function act(action)
    local bot = GetBot()
    action_type = action.actionType
    if action_type == 'DOTA_UNIT_ORDER_NONE' then
        DebugDrawCircle(bot:GetLocation(), 50, 127, 127, 127)
    elseif  action_type == 'DOTA_UNIT_ORDER_MOVE_TO_POSITION' then
        move_location = Vector(action.moveToLocation.location.x, action.moveToLocation.location.y)
        DebugDrawLine(bot:GetLocation(), move_location, 255, 255, 255)
        bot:Action_MoveDirectly(move_location)
    elseif  action_type == 'DOTA_UNIT_ORDER_ATTACK_TARGET' then
        if action.attackTarget.target == -1 then  -- Invalid target. Do nothing.
            do return end
        end
        unit = GetBotByHandle(action.attackTarget.target)
        DebugDrawCircle(unit:GetLocation(), 50, 255, 0, 0)
        bot:Action_AttackUnit(unit, action.attackTarget.once)
    else
        print('Invalid action_type=', action_type)
    end
end


local function get_new_action(dota_time)
    -- print('(lua) get_new_action @', dota_time)
    local file_fn = nil
    while true do
        -- Try to load the file first
        while true do
            file_fn = loadfile(ACTION_FILENAME)
            if file_fn ~= nil then break end
        end
        -- Execute the file_fn; this loads contents into `data`.
        local data = file_fn()
        if data ~= nil then
            local data, pos, err = dkjson.decode(data, 1, nil)
            if err then
                print("(lua) JSON Decode Error=", err, " at pos=", pos)
            end
            if data.dota_time == dota_time then
                return data
            end
        end
    end
end


local function data_from_file(filename)
    -- Get the response from a file, while waiting for the file.
    print('(lua) looking for loadfile =', filename)
    local file_fn = nil
    while true do
        while true do
            file_fn = loadfile(filename)
            if file_fn ~= nil then break end
        end
        -- Execute the file_fn; this loads contents into `data`.
        local data = file_fn()
        if data ~= nil then
            local data, pos, err = dkjson.decode(data, 1, nil)
            if err then
                print("(lua) JSON Decode Error=", err " at pos=", pos)
            end
            return data
        end
    end
end


function dump(o, d)
    print('dump d=', d)
    if d == nil then
        d = 0

    end
    indent = string.rep('  ', d)
    if type(o) == 'table' then
       local s = '{\n'
       for k,v in pairs(o) do
          if type(k) ~= 'number' then k = '"'..k..'"' end
          s = s .. indent .. '[' .. k .. '] = ' .. dump(v, d + 1) .. ',\n'
       end
       return s .. indent .. '}'
    else
       return tostring(o)
    end
end


-- This table keeps track of which time corresponds to which fn_call. 
local dota_time_to_step_map = {}
local worldstate_step_offset = nil
local step = 0


function Think()
    step = step + 1
    if GetTeam() == TEAM_DIRE then
        -- For now, just focus on radiant. We can add DIRE action files some time later.
        do return end
    end

    local dota_time = DotaTime()
    local game_state = GetGameState()

    -- Only keep track of this for calibration purposes.
    if live_config == nil then
        dota_time_to_step_map[dota_time] = step
    end

    -- print('(lua) Think() dota_time=', dota_time, 'game_state=', game_state, 'step=', step)

    -- To guarantee the dotaservice has received a worldstate, skip this function that amount
    -- of times on first run.
    if step == config.ticks_per_observation then
        -- When we went through exactly this amount calls, it's guaranteed the dotaservice has
        -- received at least one tick, from which we can calibrate.

        local status = {}
        status.dota_time = dota_time
        status.step = step
        print('LUARDY', json.encode(status))

        -- The live configuration gives us back the last time at which dota sent out a 
        -- world state signal.
        live_config = data_from_file(LIVE_CONFIG_FILENAME)
        print('(lua) live_config =', dump(live_config))

        -- We now relate when this was sent out, to the step we were at.
        worldstate_step_offset = dota_time_to_step_map[live_config.calibration_dota_time]
    end

    if worldstate_step_offset == nil then
        do return end
    end

    if ((step - worldstate_step_offset) % config.ticks_per_observation) == 0 then
        -- print('(lua) Expecting state @ step=', step, 'dota_time=', dota_time)
        -- TODO(tzaman): read the action file here, and check that it contains an
        -- action with the right timestep.
        local action = get_new_action(dota_time)
        -- print('(lua) action =', dump(action))
        -- debug_text = dump(action)
        debug_text = pprint.pformat(action)
        act(action)
    end
    if debug_text ~= nil then
        DebugDrawText(8, 90, debug_text, 255, 255, 255)
    end
end
