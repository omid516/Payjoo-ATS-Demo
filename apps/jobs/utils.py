import openpyxl
from django.db import transaction
from django.utils import timezone
from .models import CentralCompetency, JobOpportunityStage, AssessmentCompetency, JobOpportunityCompetency

def normalize_persian_digits(s):
    if not s:
        return ''
    s = str(s).strip()
    for fa, en in zip('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'):
        s = s.replace(fa, en)
    return s

def clean_cell_value(val):
    if val is None:
        return ''
    return str(val).strip()

def parse_competencies_excel(file_path):
    """
    Parses شایستگی ها.xlsx and imports/updates the CentralCompetency table.
    Returns a dict with import statistics.
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    if 'Result' not in wb.sheetnames:
        raise ValueError("شیت با نام 'Result' در فایل اکسل یافت نشد.")
    
    ws = wb['Result']
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("فایل اکسل خالی است.")
        
    headers = [clean_cell_value(h) for h in rows[0]]
    
    # Helper to find column index (case and space insensitive, handles common typos)
    def find_col(names):
        for name in names:
            name_clean = name.replace(" ", "").replace("ی", "ي").replace("ک", "ك")
            for idx, h in enumerate(headers):
                h_clean = h.replace(" ", "").replace("ی", "ي").replace("ک", "ك")
                if h_clean == name_clean:
                    return idx
        return -1

    col_map = {
        'post_code': find_col(['کد پست']),
        'post_title': find_col(['پست']),
        'code': find_col(['کد شایستگی', 'کد شايستگي']),
        'old_code': find_col(['کد شایستگی قدیم', 'کد شايستگي قديم']),
        'title': find_col(['شایستگی', 'شايستگي']),
        'category_raw': find_col(['طبقه']),
        'cluster_raw': find_col(['خوشه']),
        'importance_raw': find_col(['اهمیت شایستگی', 'اهميت شايستگي']),
        'level_raw': find_col(['سطح شایستگی', 'سطح شايستگي']),
        'management_code': find_col(['کد مدیریت', 'کد  مديريت', 'کد مديريت']),
        'management_name': find_col(['مدیریت', 'مديريت']),
        'vice_president_code': find_col(['کد معاونت']),
        'vice_president_name': find_col(['معاونت']),
        'section_code': find_col(['کد قسمت']),
        'section_name': find_col(['قسمت']),
        'cost_center_code': find_col(['کد مرکز هزینه', 'کد مرکز هزينه']),
        'cost_center_name': find_col(['مرکز هزینه', 'مرکز هزينه']),
    }
    
    # Required columns validation
    required = ['post_code', 'code', 'title', 'category_raw']
    for req in required:
        if col_map[req] == -1:
            raise ValueError(f"ستون حیاتی '{req}' (یا معادل فارسی آن) در اکسل پیدا نشد.")

    created_count = 0
    updated_count = 0
    skipped_count = 0
    seen_keys = set()
    
    with transaction.atomic():
        for row_idx, row in enumerate(rows[1:], start=2):
            if not row or not any(row):
                continue
                
            def get_val(key):
                idx = col_map[key]
                if idx == -1 or idx >= len(row):
                    return ''
                return clean_cell_value(row[idx])
                
            post_code = normalize_persian_digits(get_val('post_code'))
            code = normalize_persian_digits(get_val('code'))
            title = get_val('title')
            category_raw = get_val('category_raw')
            
            if not post_code or not code or not title or not category_raw:
                skipped_count += 1
                continue
                
            # Parse competency type from category_raw (first two letters, e.g. KN, SK, AB...)
            comp_type = category_raw[:2].upper()
            valid_types = ['KN', 'SK', 'AB', 'GE', 'ST', 'PR', 'CQ', 'IN']
            if comp_type not in valid_types:
                # Try fallback from code prefix
                code_prefix = code[:2].upper()
                if code_prefix in valid_types:
                    comp_type = code_prefix
                else:
                    comp_type = 'GE' # fallback to general
                    
            # Parse importance
            importance_raw = get_val('importance_raw')
            importance = 3 # default: minimal
            if '1' in importance_raw or 'محوری' in importance_raw:
                importance = 1
            elif '2' in importance_raw or 'تکلیف' in importance_raw:
                importance = 2
            elif '3' in importance_raw or 'حداقلی' in importance_raw:
                importance = 3
                
            # Parse level
            level_raw = get_val('level_raw')
            level = 1 # default: familiarity
            if '3' in level_raw or 'تسلط' in level_raw:
                level = 3
            elif '2' in level_raw or 'توانایی' in level_raw or 'توانايي' in level_raw:
                level = 2
            elif '1' in level_raw or 'آشنایی' in level_raw or 'آشنايي' in level_raw:
                level = 1

            key = (post_code, code)
            seen_keys.add(key)
            
            # Find existing active or deleted competency with same post_code and code
            comp = CentralCompetency.all_objects.filter(post_code=post_code, code=code).first()
            
            data = {
                'post_title': get_val('post_title'),
                'old_code': normalize_persian_digits(get_val('old_code')),
                'title': title,
                'competency_type': comp_type,
                'category_raw': category_raw,
                'cluster_raw': get_val('cluster_raw'),
                'importance': importance,
                'level': level,
                'management_code': normalize_persian_digits(get_val('management_code')),
                'management_name': get_val('management_name'),
                'vice_president_code': normalize_persian_digits(get_val('vice_president_code')),
                'vice_president_name': get_val('vice_president_name'),
                'section_code': normalize_persian_digits(get_val('section_code')),
                'section_name': get_val('section_name'),
                'cost_center_code': normalize_persian_digits(get_val('cost_center_code')),
                'cost_center_name': get_val('cost_center_name'),
                'is_deleted': False,
                'deleted_at': None
            }
            
            if comp:
                # Update
                changed = False
                for field, val in data.items():
                    if getattr(comp, field) != val:
                        setattr(comp, field, val)
                        changed = True
                if changed:
                    comp.save()
                    updated_count += 1
            else:
                # Create
                CentralCompetency.objects.create(
                    post_code=post_code,
                    code=code,
                    **data
                )
                created_count += 1
                
        # Soft delete competencies that are NOT in the uploaded file
        # Retrieve all currently active competencies
        active_comps = CentralCompetency.objects.filter(is_deleted=False)
        deleted_count = 0
        for comp in active_comps:
            if (comp.post_code, comp.code) not in seen_keys:
                comp.delete()
                deleted_count += 1
                
    return {
        'created': created_count,
        'updated': updated_count,
        'deleted': deleted_count,
        'skipped': skipped_count
    }


def calculate_assessment_plan(competencies, custom_weights=None, custom_passing_scores=None):
    """
    Takes a list/queryset of JobOpportunityCompetency and calculates:
    - required stages and their weights (summing to 100%)
    - competencies mapped to each stage with their relative weights within the stage
    - cutoff score for each stage
    
    Returns:
    - dict: {
        'stages': {
            'EXAM': {'name': 'آزمون کتبی', 'weight': percent, 'min_limit': 20, 'max_limit': 50, 'passing_score': 60, 'competencies': [...]},
            ...
        },
        'errors': []
      }
    """
    # 1. Define Stage Constraints
    # Stage limits: (min, max)
    STAGE_LIMITS = {
        'EXAM': (20, 50),
        'SKILL_TEST': (20, 40),
        'INTERVIEW': (10, 25),
        'ASSESSMENT': (15, 40)
    }
    
    STAGE_NAMES = {
        'EXAM': 'آزمون کتبی',
        'SKILL_TEST': 'آزمون مهارتی',
        'INTERVIEW': 'مصاحبه تخصصی',
        'ASSESSMENT': 'کانون ارزیابی'
    }

    # 2. Filter competencies by type and calculate individual competency weights
    # Importance Weight: Core (1) -> 3, Duty-based (2) -> 2, Minimal (3) -> 1
    # Proficiency Weight: Mastery (3) -> 3, Ability (2) -> 2, Familiarity (1) -> 1
    # Comp Weight = ImportanceWeight * ProficiencyWeight
    
    valid_competencies = []
    has_kn = False
    has_sk_ab = False
    has_ge_st = False
    
    for comp in competencies:
        ctype = comp.competency_type
        if ctype in ['PR', 'CQ', 'IN']:
            continue # ignore for now
            
        imp_weight = 3 if comp.importance == 1 else (2 if comp.importance == 2 else 1)
        prof_weight = comp.level # Already 1, 2, 3
        weight = imp_weight * prof_weight
        
        valid_competencies.append({
            'code': comp.code,
            'title': comp.title,
            'type': ctype,
            'weight': weight,
            'level': comp.level
        })
        
        if ctype == 'KN':
            has_kn = True
        elif ctype in ['SK', 'AB']:
            has_sk_ab = True
        elif ctype in ['GE', 'ST']:
            has_ge_st = True

    # 3. Determine active stages based on rules
    active_stage_keys = set()
    if has_kn:
        active_stage_keys.add('EXAM')
    if has_sk_ab:
        active_stage_keys.add('SKILL_TEST')
        active_stage_keys.add('INTERVIEW') # Required if SK or AB exists
    if has_ge_st:
        active_stage_keys.add('ASSESSMENT')
        
    if not active_stage_keys:
        return {'stages': {}, 'errors': ["هیچ شایستگی معتبری برای تعیین مراحل ارزیابی انتخاب نشده است."]}

    # 4. Aggregate weights to stages
    # - KN -> Written test (EXAM)
    # - SK/AB -> Skills test (SKILL_TEST) and Technical interview (INTERVIEW)
    # - GE/ST -> Assessment Center (ASSESSMENT)
    stage_raw_scores = {k: 0.0 for k in active_stage_keys}
    stage_competencies = {k: [] for k in active_stage_keys}
    
    for comp in valid_competencies:
        ctype = comp['type']
        if ctype == 'KN':
            if 'EXAM' in stage_raw_scores:
                stage_raw_scores['EXAM'] += comp['weight']
                stage_competencies['EXAM'].append(comp)
        elif ctype in ['SK', 'AB']:
            # Full weight goes to both Skills Test and Technical Interview
            if 'SKILL_TEST' in stage_raw_scores:
                stage_raw_scores['SKILL_TEST'] += comp['weight']
                stage_competencies['SKILL_TEST'].append(comp)
            if 'INTERVIEW' in stage_raw_scores:
                stage_raw_scores['INTERVIEW'] += comp['weight']
                stage_competencies['INTERVIEW'].append(comp)
        elif ctype in ['GE', 'ST']:
            if 'ASSESSMENT' in stage_raw_scores:
                stage_raw_scores['ASSESSMENT'] += comp['weight']
                stage_competencies['ASSESSMENT'].append(comp)

    # 5. Convert to percentage weights with constraints
    errors = []
    int_w = {}
    
    if custom_weights:
        # Parse and validate custom manual weights
        for k in active_stage_keys:
            val = custom_weights.get(k)
            if val is not None and str(val).strip() != '':
                try:
                    val_int = int(val)
                except (ValueError, TypeError):
                    errors.append(f"وزن وارد شده برای مرحله {STAGE_NAMES[k]} نامعتبر است.")
                    val_int = 0
                
                min_val, max_val = STAGE_LIMITS[k]
                if val_int < min_val:
                    errors.append(f"وزن مرحله {STAGE_NAMES[k]} نمی‌تواند کمتر از {min_val}٪ باشد.")
                elif val_int > max_val:
                    errors.append(f"وزن مرحله {STAGE_NAMES[k]} نمی‌تواند بیشتر از {max_val}٪ باشد.")
                
                int_w[k] = val_int
            else:
                errors.append(f"وزن مرحله {STAGE_NAMES[k]} وارد نشده است.")
                int_w[k] = 0
                
        if not errors:
            total_custom = sum(int_w.values())
            if total_custom != 100:
                errors.append(f"مجموع اوزان مراحل ارزیابی باید دقیقاً ۱۰۰٪ باشد. (مجموع فعلی: {total_custom}٪)")
    else:
        # Standard automated clipping & normalization algorithm
        w = {k: stage_raw_scores[k] for k in active_stage_keys}
        total_raw = sum(w.values())
        
        if total_raw == 0:
            w = {k: 100.0 / len(active_stage_keys) for k in active_stage_keys}
        else:
            w = {k: (val / total_raw) * 100.0 for k, val in w.items()}
            
        # Iterative clamping
        for _ in range(10):
            clamped = {}
            for k in active_stage_keys:
                min_val, max_val = STAGE_LIMITS[k]
                clamped[k] = max(min_val, min(max_val, w[k]))
                
            clamped_sum = sum(clamped.values())
            diff = 100.0 - clamped_sum
            
            if abs(diff) < 0.01:
                w = clamped
                break
                
            if diff > 0:
                adjustable = {k: STAGE_LIMITS[k][1] - clamped[k] for k in active_stage_keys if clamped[k] < STAGE_LIMITS[k][1]}
                total_adj = sum(adjustable.values())
                if total_adj == 0:
                    w = {k: (val / clamped_sum) * 100.0 for k, val in clamped.items()}
                    break
                w = {k: clamped[k] + (adjustable.get(k, 0.0) / total_adj) * diff for k in active_stage_keys}
            else:
                adjustable = {k: clamped[k] - STAGE_LIMITS[k][0] for k in active_stage_keys if clamped[k] > STAGE_LIMITS[k][0]}
                total_adj = sum(adjustable.values())
                if total_adj == 0:
                    w = {k: (val / clamped_sum) * 100.0 for k, val in clamped.items()}
                    break
                w = {k: clamped[k] + (adjustable.get(k, 0.0) / total_adj) * diff for k in active_stage_keys}

        # Integer rounding
        int_w = {k: int(round(val)) for k, val in w.items()}
        diff = 100 - sum(int_w.values())
        if diff != 0:
            # Find candidates for adjustment: stages that won't violate their limits if we add/subtract diff
            candidates = []
            for k in active_stage_keys:
                min_val, max_val = STAGE_LIMITS[k]
                new_val = int_w[k] + diff
                if min_val <= new_val <= max_val:
                    candidates.append(k)
            
            if candidates:
                # Adjust the candidate with the largest fractional part
                best_candidate = max(candidates, key=lambda k: w[k] - int_w[k] if diff > 0 else int_w[k] - w[k])
                int_w[best_candidate] += diff
            else:
                # Fallback to the stage with the largest weight that has space to move
                fallback_stage = max(active_stage_keys, key=lambda k: w[k])
                int_w[fallback_stage] += diff

    # 6. Build final output stages
    result_stages = {}
    for k in active_stage_keys:
        # Calculate competency weights within this stage
        s_comps = stage_competencies[k]
        s_total_comp_w = sum(c['weight'] for c in s_comps)
        
        computed_comps = []
        for c in s_comps:
            c_rel_w = int(round((c['weight'] / s_total_comp_w) * 100)) if s_total_comp_w > 0 else 100
            computed_comps.append({
                'code': c['code'],
                'title': c['title'],
                'type': c['type'],
                'weight': c_rel_w,
                'level': c['level']
            })
            
        # Rounding check for competencies within the stage
        comp_diff = 100 - sum(cc['weight'] for cc in computed_comps)
        if comp_diff != 0 and computed_comps:
            computed_comps[0]['weight'] += comp_diff
            
        min_val, max_val = STAGE_LIMITS[k]
        
        # Calculate default passing score: 50 + (average level * 10)
        avg_level = sum(c['level'] for c in s_comps) / len(s_comps) if s_comps else 1.0
        default_score = int(round(50 + avg_level * 10))
        
        passing_score = default_score
        if custom_passing_scores and k in custom_passing_scores:
            val = custom_passing_scores[k]
            if val is not None and str(val).strip() != '':
                try:
                    val_int = int(val)
                    passing_score = val_int
                    if not (0 <= val_int <= 100):
                        errors.append(f"حد نصاب قبولی برای مرحله {STAGE_NAMES[k]} باید بین ۰ و ۱۰۰ باشد.")
                except (ValueError, TypeError):
                    errors.append(f"حد نصاب قبولی وارد شده برای مرحله {STAGE_NAMES[k]} نامعتبر است.")
                    passing_score = val

        result_stages[k] = {
            'name': STAGE_NAMES[k],
            'weight': int_w[k],
            'min_limit': min_val,
            'max_limit': max_val,
            'passing_score': passing_score,
            'competencies': computed_comps
        }
        
    return {
        'stages': result_stages,
        'errors': errors
    }


def suggest_workflow_templates(active_stages):
    """
    Given a set or list of active stage types (e.g. {'EXAM', 'INTERVIEW'}),
    find and return the active WorkflowTemplates, ranked by how well they match.
    Returns:
        List of dicts: [
            {
                'template': WorkflowTemplate instance,
                'match_percentage': float (0 to 100),
                'reasons': [str, ...],
                'is_perfect_match': bool
            },
            ...
        ]
    """
    from apps.jobs.models import WorkflowTemplate
    
    templates = WorkflowTemplate.objects.filter(is_deleted=False).prefetch_related('stages')
    suggestions = []
    
    active_set = set(active_stages)
    
    STAGE_NAMES = {
        'EXAM': 'آزمون کتبی',
        'SKILL_TEST': 'آزمون مهارتی',
        'INTERVIEW': 'مصاحبه تخصصی',
        'ASSESSMENT': 'کانون ارزیابی'
    }
    
    for t in templates:
        t_stages = t.stages.filter(is_deleted=False)
        # Get set of stage types in the template, ignoring SCREENING and OTHER
        t_set = set(s.stage_type for s in t_stages if s.stage_type not in ['SCREENING', 'OTHER'])
        
        # Calculate intersection and union
        intersection = active_set.intersection(t_set)
        union = active_set.union(t_set)
        
        if not union:
            match_percent = 0.0
        else:
            match_percent = (len(intersection) / len(union)) * 100.0
            
        reasons = []
        for s_type in intersection:
            name = STAGE_NAMES.get(s_type, s_type)
            reasons.append(f"دارای {name}")
            
        missing = active_set - t_set
        for s_type in missing:
            name = STAGE_NAMES.get(s_type, s_type)
            reasons.append(f"فاقد {name}")
            
        extra = t_set - active_set
        for s_type in extra:
            name = STAGE_NAMES.get(s_type, s_type)
            reasons.append(f"اضافه: {name}")
            
        is_perfect_match = (active_set == t_set)
        
        suggestions.append({
            'template': t,
            'match_percentage': int(match_percent),
            'is_perfect_match': is_perfect_match,
            'reasons': reasons
        })
        
    # Sort suggestions by perfect match (True first), then by match percentage (desc)
    suggestions.sort(key=lambda x: (x['is_perfect_match'], x['match_percentage']), reverse=True)
    return suggestions
