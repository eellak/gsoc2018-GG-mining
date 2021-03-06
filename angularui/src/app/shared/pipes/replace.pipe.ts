import { Pipe, PipeTransform  } from '@angular/core';
import { isString, isUndefined } from '../helpers/utils';

@Pipe({
  name: 'replace'
})
export class ReplacePipe implements PipeTransform {
  
  transform (input: any, pattern: any, replacement: any): any {
    
    if (!isString(input) || isUndefined(pattern) || isUndefined(replacement)) {
      return input;
    }
    
    return input.replace(pattern, replacement);
  }
}