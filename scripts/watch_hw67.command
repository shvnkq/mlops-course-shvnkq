#!/bin/zsh
cd "${0:A:h}/.."
clear
printf 'ДЗ6–7: ход реального поиска LoRA\nОкончание: ПОИСК ЗАВЕРШЁН / state=completed в runs/sweep-status.json\n\n'
tail -n 35 -f runs/runner.log
