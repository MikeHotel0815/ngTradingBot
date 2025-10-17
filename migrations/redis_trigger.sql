-- PostgreSQL function to push commands to Redis via NOTIFY
-- This will be called by a trigger when a command is inserted

CREATE OR REPLACE FUNCTION notify_command_created()
RETURNS TRIGGER AS $$
DECLARE
    cmd_json TEXT;
    account_num BIGINT;
BEGIN
    -- Get MT5 account number
    SELECT mt5_account_number INTO account_num
    FROM accounts 
    WHERE id = NEW.account_id;
    
    -- Build command JSON
    cmd_json := json_build_object(
        'id', NEW.id::text,
        'type', NEW.command_type,
        'account_id', NEW.account_id,
        'account_number', account_num,
        'payload', NEW.payload
    )::text;
    
    -- Send notification that will be picked up by Python
    PERFORM pg_notify('command_created', cmd_json);
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS command_created_trigger ON commands;
CREATE TRIGGER command_created_trigger
    AFTER INSERT ON commands
    FOR EACH ROW
    EXECUTE FUNCTION notify_command_created();
