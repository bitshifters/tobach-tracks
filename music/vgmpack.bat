

for %%x in (vgm\*.vgm) do c:\python27\python.exe ..\bin\vgmconverter.py "%%x" -t bbc -q 50 -r "vgm_out\%%~nx.bin" -o "vgm_out\%%~nx.vgm" 
for %%x in (vgm_out\*.bin) do ..\bin\exomizer.exe raw -c -m 1024 "%%x" -o "vgm_out\%%~nx.bin.exo"