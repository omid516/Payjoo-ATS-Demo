"""
Management command: fix_missing_stage_states
ایجاد ApplicationStageState برای متقاضیانی که current_stage دارند
ولی stage state مربوطه در دیتابیس وجود ندارد.
(ناشی از import تاریخی که current_stage را مستقیم set کرده)
"""
from django.core.management.base import BaseCommand
from apps.candidates.models import JobApplication, ApplicationStageState


class Command(BaseCommand):
    help = 'ایجاد stage state برای متقاضیانی که current_stage دارند ولی stage state مربوطه ندارند'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='فقط گزارش بده، تغییری ایجاد نکن',
        )
        parser.add_argument(
            '--job-code',
            type=str,
            help='فقط برای یک فرصت شغلی خاص (کد شغل)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        job_code = options.get('job_code')

        qs = JobApplication.objects.filter(
            is_deleted=False,
            status=JobApplication.STATUS_IN_PROGRESS,
        ).select_related('current_stage', 'candidate', 'job')

        if job_code:
            qs = qs.filter(job__code=job_code)
            self.stdout.write(f'فیلتر بر اساس کد شغل: {job_code}')

        total = qs.count()
        self.stdout.write(f'بررسی {total} متقاضی IN_PROGRESS...')

        created_count = 0
        skipped_count = 0
        no_current_stage = 0

        for app in qs.iterator(chunk_size=200):
            cs = app.current_stage
            if not cs:
                no_current_stage += 1
                continue

            # بررسی وجود stage state برای current_stage
            exists = ApplicationStageState.objects.filter(
                application=app,
                stage=cs,
                is_deleted=False,
            ).exists()

            if exists:
                skipped_count += 1
                continue

            # stage state وجود نداره — بساز
            if not dry_run:
                ApplicationStageState.objects.create(
                    application=app,
                    stage=cs,
                    status=ApplicationStageState.STATUS_PENDING,
                )
            created_count += 1

            if created_count % 100 == 0:
                self.stdout.write(f'  ساخته شد: {created_count}...')

        self.stdout.write(self.style.SUCCESS(
            f'\nنتیجه:'
            f'\n  ساخته شد: {created_count}'
            f'\n  از قبل موجود (skip): {skipped_count}'
            f'\n  بدون current_stage: {no_current_stage}'
            f'\n  {"[DRY RUN - تغییری ذخیره نشد]" if dry_run else "تغییرات ذخیره شد ✓"}'
        ))
