import openpyxl

wb = openpyxl.load_workbook('/Users/omidsalehi/Desktop/ATS/شایستگی ها.xlsx', read_only=True)
ws = wb['Result']

unique_types = set()
unique_classes = set()
unique_importances = set()
unique_levels = set()

row_iter = ws.iter_rows(values_only=True)
headers = next(row_iter)

# Headers mapping:
# Col 0: کد پست
# Col 1: پست
# Col 2: کد شايستگي
# Col 3: کد شايستگي قديم
# Col 4: شايستگي
# Col 5: نوع شايستگي
# Col 6: طبقه
# Col 7: خوشه
# Col 8: شايستگي  از تاريخ
# Col 9: شايستگي  تا تاريخ
# Col 10: اهميت شايستگي
# Col 11: سطح شايستگي

for row in row_iter:
    if not row or not any(row):
        continue
    unique_types.add(row[5])
    unique_classes.add(row[6])
    unique_importances.add(row[10])
    unique_levels.add(row[11])

print("Unique columns:")
print("نوع شایستگی:", unique_types)
print("طبقه:", unique_classes)
print("اهمیت شایستگی:", unique_importances)
print("سطح شایستگی:", unique_levels)
