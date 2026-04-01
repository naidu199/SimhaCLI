"""Test script to verify set_config_value preserves existing config."""
import tempfile
from pathlib import Path
from config.loader import set_config_value

def test_set_config_value():
    # Create a temporary config file with mixed content
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.toml"
        
        # Write a sample config with comments, multiple sections, and various data types
        original_content = """# This is a comment at the top
api_key = "sk-original-key"

[model]
name = "original-model"
temperature = 0.5

# A commented out key
# allowed_user_ids = [123]

[mcp_servers.github]
command = "npx"

# Another section with a boolean
[hooks_enabled]
value = true
"""
        config_path.write_text(original_content, encoding="utf-8")
        
        # Set a new Telegram config value (string)
        set_config_value("telegram", "bot_token", "new-token-123")
        
        # Set a list value
        set_config_value("telegram", "allowed_user_ids", [123456, 789012])
        
        # Read back the modified content
        modified_content = config_path.read_text(encoding="utf-8")
        
        print("=== ORIGINAL CONTENT ===")
        print(original_content)
        print("\n=== MODIFIED CONTENT ===")
        print(modified_content)
        
        # Assertions
        assert "# This is a comment at the top" in modified_content, "Top comment lost"
        assert 'api_key = "sk-original-key"' in modified_content, "Existing api_key lost"
        assert '[model]' in modified_content, "Model section lost"
        assert 'name = "original-model"' in modified_content, "Model settings lost"
        assert '[mcp_servers.github]' in modified_content, "MCP section lost"
        assert "[telegram]" in modified_content, "Telegram section missing"
        assert 'bot_token = "new-token-123"' in modified_content, "Bot token not set correctly"
        assert "allowed_user_ids = [123456, 789012]" in modified_content, "Allowed user IDs not set correctly"
        assert "# allowed_user_ids = [123]" in modified_content, "Commented original line lost (should be preserved)"
        
        print("\n✅ All assertions passed!")

if __name__ == "__main__":
    test_set_config_value()