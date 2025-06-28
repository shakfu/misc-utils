#!/usr/bin/env sh

COLOR_BOLD_YELLOW="\033[1;33m"
COLOR_BOLD_BLUE="\033[1;34m"
COLOR_BOLD_MAGENTA="\033[1;35m"
COLOR_BOLD_CYAN="\033[1;36m"
COLOR_BOLD_RED="\033[1;31m"
COLOR_BOLD_WHITE="\033[1m"
COLOR_RESET="\033[m"



function section {
    echo
    echo $COLOR_BOLD_MAGENTA$1 $COLOR_RESET
    echo "----------------------------------------------------------------------------"
}

function info {
    echo
    echo "$COLOR_BOLD_CYAN$1 $COLOR_RESET"
    echo
}

function finished {
    echo
    echo $COLOR_BOLD_WHITE"[DONE]"$COLOR_RESET
    echo
}


function update_brew {
    info "updating homebrew" && \
    brew update && brew upgrade
}
 
function update_bun {
    info "updating bun" && \
    bun upgrade
}

function update_deno {
    info "updating deno" && \
    deno upgrade
}

function update_rustup {
    info "updating rustup" && \
    rustup update
}

function update_src
{
    info "updating src" && \
    cd $HOME/src && \
    for project in `ls -d *`; do
        if test -d $project; then
            echo "project: $project"
            for item in `ls -A $HOME/src/$project`; do
                if [[ $item == ".git/" ]]; then
                    cd $project && \
                    git pull && \
                    cd $HOME/src
                else 
                    continue
                fi
            done
        fi
    done
}


function update_src
{
    info "updating src"
    cd "$HOME/src" || return 1
    
    for project in */; do
        project="${project%/}"
        if [ -d "$project" ] && [ -d "$project/.git" ]; then
            echo "project: $project"
            cd "$project" || continue
            git pull
            echo
            cd "$HOME/src" || return 1
        fi
    done
}


function main {
    section "updating components"
    update_brew && \
    update_bun && \
    update_deno && \
    update_rustup && \
    update_src && \
    finished
}

main


