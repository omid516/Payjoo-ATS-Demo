from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied

class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        return super().update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()

class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)

class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name="حذف شده")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="تاریخ حذف")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاریخ ویرایش")

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at', 'updated_at'])

    def hard_delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        audit_enabled = getattr(self, 'audit_log_enabled', True)
        is_new = self.pk is None
        old_instance = None

        if audit_enabled and not is_new:
            try:
                old_instance = self.__class__.all_objects.get(pk=self.pk)
            except self.__class__.DoesNotExist:
                pass

        super().save(*args, **kwargs)

        if not audit_enabled:
            return

        # Import helper inside method to prevent circular imports
        from apps.core.utils import log_action
        
        if is_new:
            changes = {}
            for field in self._meta.fields:
                if field.primary_key:
                    continue
                val = getattr(self, field.name)
                if val is not None:
                    changes[field.name] = str(val)
            log_action(AuditLog.ACTION_CREATE, self, changes)
        else:
            changes = {}
            if old_instance:
                for field in self._meta.fields:
                    if field.primary_key:
                        continue
                    old_val = getattr(old_instance, field.name)
                    new_val = getattr(self, field.name)
                    if old_val != new_val:
                        changes[field.name] = {
                            'old': str(old_val) if old_val is not None else None,
                            'new': str(new_val) if new_val is not None else None
                        }
            if changes:
                # Detect specific actions
                action_type = AuditLog.ACTION_UPDATE
                if 'is_deleted' in changes and changes['is_deleted']['new'] == 'True':
                    action_type = AuditLog.ACTION_DELETE
                elif any(k in changes for k in ['score', 'total_score', 'weight']):
                    action_type = AuditLog.ACTION_SCORE_CHANGE
                elif 'status' in changes or 'application_status' in changes:
                    action_type = AuditLog.ACTION_STATUS_CHANGE

                log_action(action_type, self, changes)


class AuditLog(models.Model):
    ACTION_CREATE = 'CREATE'
    ACTION_UPDATE = 'UPDATE'
    ACTION_DELETE = 'DELETE'
    ACTION_SCORE_CHANGE = 'SCORE_CHANGE'
    ACTION_STATUS_CHANGE = 'STATUS_CHANGE'

    ACTION_CHOICES = [
        (ACTION_CREATE, 'ایجاد'),
        (ACTION_UPDATE, 'ویرایش'),
        (ACTION_DELETE, 'حذف'),
        (ACTION_SCORE_CHANGE, 'تغییر امتیاز'),
        (ACTION_STATUS_CHANGE, 'تغییر وضعیت'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="کاربر")
    action_type = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="نوع عملیات")
    model_name = models.CharField(max_length=100, verbose_name="نام مدل")
    object_id = models.CharField(max_length=255, verbose_name="شناسه شی")
    changes = models.JSONField(verbose_name="تغییرات")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="آدرس IP")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="زمان ثبت")

    class Meta:
        verbose_name = "لاگ حسابرسی"
        verbose_name_plural = "لاگ‌های حسابرسی"
        ordering = ['-timestamp']

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied("امکان ویرایش لاگ‌های حسابرسی وجود ندارد.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("امکان حذف لاگ‌های حسابرسی وجود ندارد.")
