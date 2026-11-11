"""SQL helpers read by every row-level-security policy."""
from django.db import migrations

from apps.core.db import CURRENT_USER_FUNCTION_SQL, HAS_CAPABILITY_FUNCTION_SQL


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.RunSQL(HAS_CAPABILITY_FUNCTION_SQL, "DROP FUNCTION IF EXISTS brite_has_capability(text, text);"),
        migrations.RunSQL(CURRENT_USER_FUNCTION_SQL, "DROP FUNCTION IF EXISTS brite_current_user_id();"),
    ]
